// Exercise the packaged frontend and actual WASM/AudioWorklets with a mocked
// desktop IPC host. Speakers stay muted; this does not test a CPAL device.
const {chromium, webkit} = require('playwright');
const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');
const http = require('node:http');

const root = path.resolve(__dirname, '..');
const nativeSource = require('node:fs').readFileSync(path.join(root,'src-tauri/src/audio.rs'),'utf8');
const nativeCredits = Number(/const QUEUE_PACKETS: usize = (\d+);/.exec(nativeSource)[1]);
const nativePrefillPackets = Number(/const PREFILL_PACKETS: usize = (\d+);/.exec(nativeSource)[1]);
const options = {out:path.join(root,'docs/desktop_browser_20261115.json'), screenshots:null};
for(let index=2;index<process.argv.length;index++) {
  const name=process.argv[index].replace(/^--/,'');
  assert(Object.hasOwn(options,name),`Unknown option: ${name}`);
  assert(process.argv[index+1],`Missing value: ${name}`);
  options[name]=path.resolve(process.argv[++index]);
}
const mime = {'.html':'text/html','.js':'text/javascript','.css':'text/css','.wasm':'application/wasm',
  '.json':'application/json','.webp':'image/webp','.png':'image/png','.svg':'image/svg+xml'};
async function run(name, engine, backend) {
  const browser=await engine.launch({headless:true});
  const page=await browser.newPage({viewport:{width:1280,height:1000},acceptDownloads:true});page.setDefaultTimeout(15000);
  const errors=[],missing=[],consoleErrors=[],checks=[];
  page.on('pageerror',error=>errors.push(error.message));
  page.on('console',message=>{if(message.type()==='error')consoleErrors.push(message.text());});
  const desktop=await fs.readFile(path.join(root,'desktop/desktop-interface.js'),'utf8');
  const overlay=(await fs.readFile(path.join(root,'desktop/synth-bridge.js'),'utf8'))+'\n;\n'+(await fs.readFile(path.join(root,'desktop/audio-interface.js'),'utf8'));
  await page.route('**/*',async route=>{
    const url=new URL(route.request().url());if(['blob:','data:'].includes(url.protocol))return route.continue();
    if(url.hostname!=='tauri.localhost')return route.abort();
    try{
      const file=url.pathname==='/desktop-audio-worklet.js'?path.join(root,'desktop/audio-worklet.js'):path.resolve(root,'dist','.'+decodeURIComponent(url.pathname==='/'?'/index.html':url.pathname));
      assert(file.startsWith(path.join(root,'dist')+path.sep)||file===path.join(root,'desktop/audio-worklet.js'));
      let body=await fs.readFile(file);if(url.pathname==='/synth-fm2608/synth.js')body=Buffer.concat([body,Buffer.from('\n;\n'+overlay)]);
      return route.fulfill({status:200,body,contentType:mime[path.extname(file)]||'application/octet-stream',headers:{'access-control-allow-origin':'*'}});
    }catch(error){missing.push(url.pathname+': '+error.message);return route.fulfill({status:404,body:'Missing asset'});}
  });
  await page.addInitScript(({backend,nativeCredits})=>{
    const audit=window.desktopAudit={calls:[],saves:[],contexts:[],worklets:[],speakerEdges:new Map(),
      pinned:false,nextRead:0,packets:0,returned:0,nativePeak:0,nativeMaxPeak:0,nativeFinite:true,nativeSession:0,failWrites:false,holdStart:false,cancelSave:false,sessions:new Map()};
    const Context=window.AudioContext??window.webkitAudioContext, Node=window.AudioWorkletNode;
    const connect=AudioNode.prototype.connect,disconnect=AudioNode.prototype.disconnect;
    window.AudioContext=class extends Context {constructor(...args){
      super(...args);audit.contexts.push(this);
      // Playwright page routes do not see AudioWorklet module fetches. Serve
      // those exact bytes through a real CORS-enabled loopback test server.
      const add=this.audioWorklet.addModule.bind(this.audioWorklet);
      this.audioWorklet.addModule=(url,...options)=>{
        const value=new URL(url,location.href);
        return add(value.hostname==='tauri.localhost'?new URL(value.pathname+value.search,backend).href:url,...options);
      };
    }};
    if(window.webkitAudioContext) window.webkitAudioContext=window.AudioContext;
    window.AudioWorkletNode=class extends Node {constructor(...args){super(...args);audit.worklets.push({node:this,name:args[1]});}};
    AudioNode.prototype.connect=function(destination,...args){
      if(destination!==this.context.destination) return connect.call(this,destination,...args);
      const analyser=this.context.createAnalyser();analyser.fftSize=4096;
      const mute=this.context.createGain();mute.gain.value=0;
      connect.call(this,analyser);connect.call(analyser,mute);connect.call(mute,destination);
      audit.speakerEdges.set(this,{analyser,mute});return destination;
    };
    AudioNode.prototype.disconnect=function(destination,...args){
      const edge=audit.speakerEdges.get(this);
      if(edge&&(arguments.length===0||destination===this.context.destination)) {
        disconnect.call(this,edge.analyser);disconnect.call(edge.analyser);disconnect.call(edge.mute);audit.speakerEdges.delete(this);
        if(arguments.length) return;
      }
      return arguments.length?disconnect.call(this,destination,...args):disconnect.call(this);
    };
    audit.webPeak=async()=>{
      const {output}=window.tetoricaSynthAudio.getOutput()??{},edge=audit.speakerEdges.get(output);
      if(!edge)return 0;const samples=new Float32Array(edge.analyser.fftSize);edge.analyser.getFloatTimeDomainData(samples);
      return samples.reduce((peak,value)=>Math.max(peak,Math.abs(value)),0);
    };
    window.__TAURI_INTERNALS__={invoke:async(command,args={},options)=>{
      audit.calls.push({command,session:args?.session,bytes:args instanceof ArrayBuffer?args.byteLength:null});
      if(command==='window_pin_state')return audit.pinned;
      if(command==='set_window_pin')return audit.pinned=args.pinned;
      if(command==='save_export_binary') {
        const length=new DataView(args).getUint32(0,true),header=JSON.parse(new TextDecoder().decode(new Uint8Array(args,4,length)));
        const bytes=new Uint8Array(args,4+length),text=new TextDecoder().decode(bytes);
        audit.saves.push({header,text,bytes:[...bytes]});return audit.cancelSave?null:'/tmp/'+header.filename;
      }
      if(command==='audio_devices')return [{id:'offline-test',name:'Offline test device',isDefault:true}];
      if(command==='audio_start') {
        if(audit.holdStart)await new Promise(resolve=>{audit.releaseStart=()=>{audit.holdStart=false;resolve();};});
        const session=`offline-${++audit.nativeSession}`;audit.sessions.set(session,{packets:0,returned:0});return {session,frames:512,credits:nativeCredits,sampleRate:48000};
      }
      if(command==='audio_stop')return null;
      if(command==='audio_write') {
        if(audit.failWrites)throw Error('Injected offline device failure');
        const session=audit.sessions.get(options.headers['x-synth-audio-session']);if(!session)throw Error('Unknown write session');const samples=new Float32Array(args),packets=args.byteLength/(512*8);session.packets+=packets;audit.packets+=packets;
        for(const value of samples){audit.nativeFinite&&=Number.isFinite(value);audit.nativePeak=Math.max(audit.nativePeak,Math.abs(value));audit.nativeMaxPeak=Math.max(audit.nativeMaxPeak,Math.abs(value));}
        return {rustMicros:100,serviceMicros:200};
      }
      if(command==='audio_poll') {
        await new Promise(resolve=>setTimeout(resolve,20));const session=audit.sessions.get(args.session);const credits=session?Math.min(nativeCredits,session.packets-session.returned):0;if(session)session.returned+=credits;
        return {credits,queuedFrames:1024,underruns:0};
      }
      if(command==='reload_window')return null;
      throw Error(`Unexpected native command: ${command}`);
    }};
  },{backend,nativeCredits});
  await page.addInitScript({content:desktop});
  const check=label=>{checks.push(label);console.log(`CHECK ${name}: ${label}`);};
  const menu = async () => {
    if (!await page.locator('#synthMenu').evaluate(node => node.open)) await page.click('#synthMenuButton');
  };
  const output = async value => {
    await menu();
    if (!await page.locator('#desktop-audio-output').evaluate(node => node.open)) await page.locator('#desktop-audio-output > summary').click();
    await page.click('#desktop-audio-' + value);
    await page.waitForFunction(value => {
      const mode = document.querySelector('#desktop-audio-mode');
      const status = document.querySelector('#desktop-audio-status').textContent;
      return mode.value === value && !mode.disabled && (value === 'native' ? status.startsWith('Native →') : status === 'Web Audio output');
    }, value);
  };
  const save = async id => {
    const before = await page.evaluate(() => desktopAudit.saves.length);
    await menu(); await page.click('#' + id);
    await page.waitForFunction(count => desktopAudit.saves.length === count + 1, before);
    return page.evaluate(() => desktopAudit.saves.at(-1));
  };
  const quiet = () => page.waitForFunction(async () => await desktopAudit.webPeak() < .000002);
  const keyboard = async (section, native = false) => {
    await page.click('#tab-' + section);
    await page.click('#stopAudio');
    await page.waitForTimeout(180);
    if (section === 'rhythm') await page.click('#channelTabs [data-channel="0"]');
    await page.evaluate(() => {desktopAudit.nativePeak = 0;});
    await page.keyboard.down('a');
    if (native) await page.waitForFunction(() => desktopAudit.nativePeak > .00001);
    else await page.waitForFunction(async () => await desktopAudit.webPeak() > .00001);
    await page.keyboard.up('a');
    await page.click('#stopAudio');
    if (!native) await quiet();
  };
  try {
    check('one existing Import/Export menu, lazy audio and desktop Pin');
    await page.goto(backend + '/index.html');
    await page.waitForFunction(() => window.tetoricaSynthAudio && document.querySelector('#synthPinButton')?.hidden === false && document.querySelector('#desktop-audio-native'));
    assert.equal(await page.title(), 'Tetorica FM2608 Synth');
    assert.equal(await page.locator('#synthMenu').count(), 1);
    assert.equal(await page.locator('[aria-label="Menu"]').count(), 1);
    assert.equal(await page.evaluate(() => desktopAudit.contexts.length), 0);
    assert.equal(await page.locator('#desktop-audio-mode').inputValue(), 'web');
    for (const expected of ['true', 'false']) {
      await page.click('#synthPinButton');
      await page.waitForFunction(expected => document.querySelector('#synthPinButton').getAttribute('aria-pressed') === expected, expected);
    }
    await page.click('#startAudio');
    await page.waitForFunction(() => document.querySelector('#startAudio').textContent === 'Audio ready');
    check('actual YM2608 WASM and FM / SSG / Rhythm / ADPCM keyboard audio');
    for (const section of ['fm', 'ssg', 'rhythm', 'adpcm']) await keyboard(section);
    assert.equal(await page.evaluate(() => desktopAudit.contexts.length), 1);
    check('native binary preset and FM exports preserve original bytes');
    const saved = await save('exportSoundButton');
    const preset = JSON.parse(saved.text);
    assert.equal(preset.format, 'tetorica-fm2608-synth');
    assert.equal(preset.fm.length, 6); assert.equal(preset.ssg.channels.length, 3);
    assert(preset.adpcm.data.length > 0);
    await page.click('#tab-fm');
    const tfi = await save('exportTfiButton');
    assert(tfi.header.filename.endsWith('.tfi')); assert(tfi.bytes.length > 20);
    const modified = structuredClone(preset);
    modified.name = 'Desktop imported sound';
    modified.fm.forEach(voice => {voice.algorithm = 6;});
    await menu();
    const chooser = page.waitForEvent('filechooser');
    await page.click('#importSoundButton');
    await (await chooser).setFiles({name:'desktop.opna.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(modified))});
    await page.waitForFunction(() => document.querySelector('#instrumentName').value === 'Desktop imported sound');
    const imported = JSON.parse((await save('exportSoundButton')).text);
    assert.deepEqual(imported, modified);
    check('Code loops and manual parameters share the same native output bus');
    await output('native');
    assert.equal(await page.evaluate(() => desktopAudit.speakerEdges.has(tetoricaSynthAudio.getOutput().output)), false);
    for (const section of ['fm', 'ssg', 'rhythm', 'adpcm']) await keyboard(section, true);
    await page.click('#tab-fm'); await page.click('#synthInputCodeTab');
    await page.locator('#synthCodeEditor').fill('const opna = await useSoundChip("ym2608");\nawait opna.noteOn(CH1,"E3");\nliveLoop("hold",async()=>{await beat(1);});\n');
    await page.evaluate(() => {desktopAudit.nativePeak = 0;});
    await page.click('#synthCodeRunButton');
    await page.waitForFunction(() => /Playing|Running/.test(document.querySelector('#synthCodeState').textContent));
    await page.waitForFunction(() => desktopAudit.nativePeak > .00001);
    await page.locator('[data-control="fm.feedback"] .param-button').last().click();
    assert.match(await page.locator('#synthCodeState').textContent(), /Playing|Running/);
    await page.click('#synthInputKeyboardTab');
    assert.match(await page.locator('#synthCodeState').textContent(), /Playing|Running/);
    await page.click('#stopAudio');
    check('VGM import saves usable Files presets and original compressed song');
    const {createOpnaFixture} = require('../tests/helpers/opna-fixture.cjs');
    const fixture = createOpnaFixture();
    await menu();
    const songChooser = page.waitForEvent('filechooser'); await page.click('#importSongButton');
    await (await songChooser).setFiles({name:'Desktop reference.vgz',mimeType:'application/octet-stream',buffer:fixture.vgz});
    await page.waitForFunction(() => document.querySelector('#songSelect').options.length === 2 && !document.querySelector('#songPlay').disabled);
    const paths = await page.locator('#opnaPresetSelect option').evaluateAll(options => options.map(option => option.value).filter(Boolean));
    assert(paths.length >= 4); assert(paths.every(value => value.startsWith('/presets/Desktop reference/')));
    await page.locator('#opnaFilesTree button[data-file-path="/vgm/Desktop reference.vgz"]').click();
    const originalSong = await save('opnaFileExportButton');
    assert.deepEqual(Buffer.from(originalSong.bytes), fixture.vgz);
    await page.locator('#opnaPresetSelect').selectOption(paths.find(value => value.includes('FM CH')));
    assert.equal(await page.locator('#tab-fm').getAttribute('aria-selected'), 'true');
    const project = await save('opnaProjectExportButton');
    assert(project.header.filename.endsWith('.zip')); assert.deepEqual(project.bytes.slice(0, 2), [80, 75]);
    check('VGM Play / Pause / Resume and paused audition remain on Native');
    await page.click('#channelTabs [data-channel="0"]');
    await page.click('#songPlay');
    await page.waitForFunction(() => document.querySelector('#referenceSong').dataset.playback === 'playing');
    await page.click('#songPause');
    await page.waitForFunction(() => document.querySelector('#referenceSong').dataset.manualReady === 'true' && document.querySelector('#referenceSong').dataset.playback === 'paused');
    const frozen = await page.locator('#songTime').textContent();
    await page.evaluate(() => {desktopAudit.nativePeak = 0;});
    await page.keyboard.down('a'); await page.waitForFunction(() => desktopAudit.nativePeak > .00001); await page.keyboard.up('a');
    assert.equal(await page.locator('#songTime').textContent(), frozen);
    await page.click('#songPlay');
    await page.waitForFunction(() => document.querySelector('#referenceSong').dataset.playback === 'playing');
    assert.equal(await page.evaluate(() => desktopAudit.speakerEdges.has(tetoricaSynthAudio.getOutput().output)), false);
    assert.equal(await page.evaluate(() => desktopAudit.contexts.length), 1);
    await page.click('#songStop');
    check('output switching stops transport and restores Web Audio without duplicate routes');
    await page.click('#songPlay');
    await page.waitForFunction(() => document.querySelector('#referenceSong').dataset.playback === 'playing');
    await output('web');
    await page.waitForFunction(() => document.querySelector('#referenceSong').dataset.playback === 'stopped');
    assert.equal(await page.evaluate(() => desktopAudit.speakerEdges.has(tetoricaSynthAudio.getOutput().output)), true);
    await keyboard('fm');
    check('native failure falls back to Web Audio and retains presets');
    await output('native');
    await page.evaluate(() => {desktopAudit.failWrites = true;});
    await page.keyboard.down('a');
    await page.waitForFunction(() => document.querySelector('#desktop-audio-status').textContent.includes('Injected offline device failure'));
    await page.keyboard.up('a');
    assert.equal(await page.locator('#desktop-audio-mode').inputValue(), 'web');
    assert.equal(await page.evaluate(() => desktopAudit.speakerEdges.has(tetoricaSynthAudio.getOutput().output)), true);
    await keyboard('fm');
    check('cancelled native save and narrow desktop layout');
    await page.evaluate(() => {desktopAudit.cancelSave = true;});
    await save('exportSoundButton');
    await page.waitForFunction(() => document.querySelector('#audioStatus').textContent === 'Save cancelled.');
    if (options.screenshots) await page.screenshot({path:path.join(options.screenshots, `desktop-${name}.png`),fullPage:true});
    await page.setViewportSize({width:390,height:900});
    await page.waitForTimeout(120);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
    assert(overflow <= 1, `Narrow desktop overflow: ${overflow}`);
    if (options.screenshots) await page.screenshot({path:path.join(options.screenshots, `desktop-${name}-narrow.png`),fullPage:true});
    assert.deepEqual(errors, []); assert.deepEqual(missing, []);
    const measurements = await page.evaluate(() => ({nativePackets:desktopAudit.packets,nativePeak:desktopAudit.nativeMaxPeak,nativeFinite:desktopAudit.nativeFinite,audioContexts:desktopAudit.contexts.length}));
    assert.equal(measurements.nativeFinite, true);
    assert(measurements.nativePeak > .00001);
    return {engine:name,checks,passed:true,mobileOverflow:overflow,nativeCredits,nativePrefillPackets,...measurements,nativeHost:'mocked Tauri IPC; no CPAL device',physicalOutput:'muted'};
  }catch(error){console.error(JSON.stringify({engine:name,audioStatus:await page.locator('#audioStatus').textContent().catch(()=>null),diagnostics:await page.evaluate(()=>({activeElement:document.activeElement?.tagName,outputMode:document.querySelector('#desktop-audio-mode')?.value,outputBusy:document.querySelector('#desktop-audio-mode')?.disabled,outputStatus:document.querySelector('#desktop-audio-status')?.textContent,activeKeys:[...document.querySelectorAll('#keyboard .is-active')].map(node=>node.dataset.key)})).catch(()=>null),errors,missing,consoleErrors}));if(options.screenshots)await page.screenshot({path:path.join(options.screenshots,`desktop-${name}-failure.png`),fullPage:true}).catch(()=>{});throw error;}
  finally{await browser.close();}
}
(async()=>{
  if(options.screenshots)await fs.mkdir(options.screenshots,{recursive:true});
  const server=http.createServer(async(request,response)=>{
    try {
      const name=decodeURIComponent(new URL(request.url,'http://localhost').pathname);
      const file=name==='/desktop-audio-worklet.js'?path.join(root,'desktop/audio-worklet.js'):path.resolve(root,'dist','.'+name);
      assert(file.startsWith(path.join(root,'dist')+path.sep)||file===path.join(root,'desktop/audio-worklet.js'));
      const bytes=await fs.readFile(file);response.writeHead(200,{'content-type':mime[path.extname(file)]||'application/octet-stream','access-control-allow-origin':'*'});response.end(bytes);
    } catch(error){response.writeHead(404,{'access-control-allow-origin':'*'});response.end('Missing test asset');}
  });
  await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',resolve);});
  try {
    const backend=`http://tauri.localhost:${server.address().port}`;
    const rows=[];for(const [name,engine] of [['chromium',chromium],['webkit',webkit]])rows.push(await run(name,engine,backend));
    await fs.mkdir(path.dirname(options.out),{recursive:true});await fs.writeFile(options.out,JSON.stringify({passed:true,rows},null,2)+'\n');
    console.log(`Desktop browser check passed: ${options.out}`);
  } finally {await new Promise(resolve=>server.close(resolve));}
})().catch(error=>{console.error(error);process.exitCode=1;});
