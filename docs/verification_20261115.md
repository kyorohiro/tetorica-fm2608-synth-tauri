# FM2608 desktop verification

Verified locally on 2026-11-15. Initial desktop app version is `0.0.1`.

## Imported Web release

- Archive is `tetorica_fm2608_synth_dev-20261115-desktop-ready_itch.zip`.
- SHA-256 is `dd1c5ea919c67c7dc683d6891e29f1815e1944a6d71fb67b7ef714a17f5c6198`.
- All 181 extracted files pass the pinned import check. The original browser
  source archive, readable module graph, SDK manifest, 38 native source inputs,
  matching YM2608 WASM, effects and synthetic rhythm sources remain included.
- The parent Web Synth has a small guarded desktop bridge. The host awaits
  output routing before keyboard / Code / song playback and invalidates stale
  starts during output changes. Normal browser pages keep their usual output.
- The imported Web files remain unchanged in `dist/`. The desktop resource
  server appends the local adapters to the FM2608 module at runtime.

## Automated checks

- Python tests pass all 33 checks for import validation, transaction rollback,
  original-source retention, local edits and synchronized version updates.
- JavaScript unit tests pass all 47 checks for Menu / Pin, native saving,
  AudioWorklet transport, routing and failure handling.
- Rust default tests pass 30 checks. Two opt-in physical-device tests are
  excluded from the default run. `cargo fmt --check` passes.
- The desktop browser suite passes nine scenarios in each of Chromium and
  WebKit. Both engines render real FM / SSG / Rhythm / ADPCM PCM. Tests cover
  Code and manual edits, Native routing, VGM import and generated presets,
  original VGZ export bytes, Play / Pause / Resume, paused audition, output
  changes, failure fallback, native export cancellation and narrow layout.
  Browser speakers are muted and Tauri IPC is mocked in this suite.
- The offline transport stress model passes with the current nine-packet
  queue, four-packet startup and batched writes. It exercises the actual
  desktop AudioWorklet against modeled IPC / device scheduling.
- Parent Web Synth app and package tests pass all 109 checks after adding
  the guarded desktop bridge.

Local evidence is retained under `artifacts/`.

| Evidence | Result |
| --- | --- |
| `unit-tests.log` | 33 Python and 47 JavaScript checks |
| `native-tests-final.log` | 30 Rust checks and two opt-in tests |
| `desktop-browser.json` | Nine scenarios in each browser |
| `desktop-browser-images/` | Desktop and narrow screenshots |
| `audio-transport.json` | Offline transport model |
| `macos-build-final.log` | Successful Release app build |
| `macos-bundle.json` | Bundle identity, version, architecture and executable hash |

## Actual macOS app

- Built the optimized arm64 app with `--bundles app --no-sign -- --locked`.
- Bundle identifier is `net.tetorica.synth-fm2608` and the displayed app is
  `Tetorica FM2608 Synth`.
- Opened the built app and verified its FM / SSG / Rhythm / ADPCM / Mixer UI.
- A single hamburger Menu contains the existing imports / exports, Audio
  output and Reload. Pin is adjacent and successfully toggles on and off.
- With playback stopped, Native output connects to the actual system output
  device at 48,000 Hz. Its status showed no buffer underruns or capture drops
  during the short connection check. Switching back restores Web Audio.
- The optional standalone `native_device_continuous` test failed while opening
  CoreAudio from the command environment. The restricted run failed to read
  output configuration, and a retry outside that restriction timed out while
  enumerating devices. This test did not reach its intended 30-second stream.
  The actual Tauri app connection above succeeded. Its log is retained as
  `artifacts/native-device-silence.log`.

The local app is at
`src-tauri/target/release/bundle/macos/Tetorica FM2608 Synth.app`.

## Pending manual and release verification

Musical listening, extended background playback and physical-device changes
remain to be checked. The local build used `--no-sign`. Signed / notarized
app and DMG builds use `deploy_mac.sh` in the user's local signing environment.
The macOS Intel, Windows and Linux workflow jobs are configured and await the
repository's first push. Publishing and tagging remain separate release work.

## FM editing readability follow-up

After the v0.0.5 release, the Web assets were updated through the normal import
workflow. The desktop app version is `0.0.5`.

- Imported `tetorica_fm2608_synth_dev-20261115-fm-controls_itch.zip`, containing
  181 verified files. SHA-256 is
  `bab890ef6999fabed440b672afa52613a314b5902dbcbd7a1262bf9b0805ab44`.
- ALGO now shows the current operator routing with parentheses, arrows and
  sums. OP1–OP4 colors match the rows, envelope controls / guides and CH3 labels.
- RS, AR, D1R, D2R, SL and RR use the envelope color category. Pitch, level
  and modulation use their existing FM2612 categories.
- The parent packaged browser suite passes 30 checks per engine, including all
  eight algorithms, exact OP colors, envelope fields, Code Live and mobile fit.
  Local screenshots are in `build/fm2608-fm-ui-packaged/` in the parent checkout.
- Desktop tests pass 33 Python and 47 JavaScript checks. The desktop browser
  suite passes nine checks per engine. Local reports are
  `artifacts/fm-ui-tests.log` and `artifacts/fm-ui-desktop-browser.json`.
- Rebuilt the local arm64 Release app with `--no-sign`. The build log is
  `artifacts/fm-ui-macos-build.log`.
