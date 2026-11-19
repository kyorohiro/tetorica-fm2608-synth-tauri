"""Import a readable FM2608 Synth release and pin all original file bytes."""
import argparse
import hashlib
import importlib.util
import io
import json
import posixpath
import re
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BROWSER_RECEIPT = 'sources/fm2608-synth-browser.json'
BROWSER_SOURCE_ARCHIVE = 'sources/fm2608-synth-browser-inputs.zip'
BROWSER_COMMON_ENTRIES = {
    'synth-fm2608/synth.js', 'synth-fm2608/synth.css',
    'js/native-fx-worklet.js',
}
BROWSER_ENTRIES = BROWSER_COMMON_ENTRIES | {'synth-fm2608/audio_worklet.js'}
LEGACY_BROWSER_ENTRIES = BROWSER_COMMON_ENTRIES | {'js/ym2608-worklet.js'}
DECLARATION_SOURCES = {
    f'playground/{name}.d.ts': f'docs/playground/{name}.d.ts'
    for name in ('tetorica-playground-globals', 'tetorica-playground-ym2608', 'tetorica-shell')
}
RHYTHM_SOURCES = {
    **{f'assets/opna-rhythm/{name}': f'assets/opna-rhythm/{name}'
       for name in ('LICENSE', 'README.md', 'generate.mjs', 'synthesis.mjs')},
    'js/tetorica_ym2608_adpcm_rom.bin': 'tetorica_src/runtime/tetorica_ym2608_adpcm_rom.bin',
}
EFFECT_INPUTS = {'LICENSE', 'scripts/build_native_audio_effect.sh'} | {
    'tetorica_src/native/audio_effect/' + name for name in (
        'compressor.c', 'compressor.h', 'eq.c', 'extra_fx.c', 'extra_fx.h',
        'gain.c', 'graph.c', 'noise.c', 'noise_gate.c', 'noise_gate.h',
        'reverb.c', 'reverb.h', 'sample.c')
}
NATIVE_REQUIRED = {
    'wasm/ym2608_wasm.cpp', 'wasm/ymfm_wasm_interface.h',
    'scripts/build_ym2608_wasm.sh', 'vendor/ymfm/ymfm_opn.cpp',
    'vendor/ymfm/ymfm_ssg.cpp', 'vendor/ymfm/ymfm_adpcm.cpp', 'vendor/ymfm/LICENSE',
}
REQUIRED = {
    'index.html', 'synth-fm2608/index.html', 'tetorica_fm2608_synth.webp', 'LICENSE',
    BROWSER_RECEIPT, BROWSER_SOURCE_ARCHIVE, *BROWSER_COMMON_ENTRIES,
    'generated/ym2608_wasm.js', 'generated/ym2608_wasm.wasm',
    'sources/YM2608.json', 'sources/YM2608.md',
    'sources/ym2608-sdk/RELEASE-MANIFEST.json', 'sources/ym2608-sdk/soundchip-sdk.json',
    'sources/code-effects/README.md', 'js/native_audio_effect.wasm',
    'licenses/ymfm/LICENSE', 'licenses/tetorica-virtual-files/LICENSE',
    'playground/vendor/fflate-LICENSE', *DECLARATION_SOURCES, *RHYTHM_SOURCES,
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def validate_release(destination, hashes):
    missing = REQUIRED - hashes.keys()
    if missing:
        raise ValueError('Expected FM2608 Synth ZIP; missing: ' + ', '.join(sorted(missing)))

    def record_ok(record):
        return (isinstance(record, dict) and type(record.get('bytes')) is int
                and record['bytes'] >= 0 and valid_hash(record.get('sha256')))

    def same_record(left, right):
        return (record_ok(left) and record_ok(right)
                and all(left[key] == right[key] for key in ('bytes', 'sha256')))

    def verify(record, name):
        safe_name(name)
        if not record_ok(record):
            raise ValueError(f'Expected a valid source record: {name}')
        if name not in hashes:
            raise ValueError(f'Missing recorded release file: {name}')
        if record['bytes'] != (destination / name).stat().st_size or record['sha256'] != hashes[name]:
            raise ValueError(f'Release source receipt mismatch: {name}')

    def records(value, label):
        if not isinstance(value, list) or not value:
            raise ValueError(f'Expected {label} source records')
        result = {}
        for record in value:
            if not record_ok(record):
                raise ValueError(f'Expected a valid {label} source record')
            name = safe_name(record.get('path'))
            if name in result:
                raise ValueError(f'Duplicate {label} source record: {name}')
            result[name] = record
        return result

    def read_json(name):
        return json.loads((destination / name).read_text(encoding='utf-8'), object_pairs_hook=unique_object)

    def build_records(value, label):
        if not isinstance(value, list) or any(not isinstance(record, dict) for record in value):
            raise ValueError(f'Expected {label} source records')
        return records([{**record, 'bytes': record.get('size')} for record in value], label)

    browser = read_json(BROWSER_RECEIPT)
    if (not isinstance(browser, dict) or type(browser.get('schemaVersion')) is not int
            or browser['schemaVersion'] != 1 or browser.get('productId') != 'tetorica-fm2608-synth'
            or browser.get('product') != 'Tetorica FM2608 Synth'):
        raise ValueError('Expected FM2608 Synth source receipt')
    builder = browser.get('builder')
    if (not isinstance(builder, dict) or builder.get('name') != 'source-copy'
            or builder.get('minify') is not False or builder.get('bundle') is not False):
        raise ValueError('Expected readable source-copy browser modules without minification or bundling')
    entries = records(browser.get('bundles'), 'browser entry')
    # The release moved its processor to an app-specific entry for audio-owned
    # ADPCM release. Accept either complete layout, never a partial/mixed list.
    # Every selected entry still has to pass the source and module hash checks.
    if entries.keys() not in (BROWSER_ENTRIES, LEGACY_BROWSER_ENTRIES):
        raise ValueError('Expected complete FM2608 Synth entry receipts')
    modules = records(browser.get('modules'), 'readable browser module')
    if not entries.keys() <= modules.keys():
        raise ValueError('Expected all browser entries in the readable module receipts')
    original = records(browser.get('originalInputs'), 'original browser input')
    for name, record in modules.items():
        verify(record, name)
        source = original.get(safe_name(record.get('sourcePath')))
        if not same_record(record, source):
            raise ValueError(f'Browser module differs from its original source receipt: {name}')
        imports = record.get('localImports', [])
        if not isinstance(imports, list):
            raise ValueError(f'Expected local module imports: {name}')
        for dependency in imports:
            if not isinstance(dependency, str) or not dependency.startswith(('./', '../')):
                raise ValueError(f'Expected a relative local module import: {name}')
            target = safe_name(posixpath.normpath(posixpath.join(
                posixpath.dirname(name), re.split(r'[?#]', dependency, maxsplit=1)[0])))
            # Emscripten factory modules have their own original input and native
            # output receipts, outside the authored browser module graph.
            if target not in modules and target != 'generated/ym2608_wasm.js':
                raise ValueError(f'Missing recorded browser module dependency: {name} -> {target}')
    for name, record in entries.items():
        verify(record, name)
        if not same_record(record, modules[name]):
            raise ValueError(f'Browser entry differs from its module receipt: {name}')

    source = browser.get('sourceArchive', {})
    if not isinstance(source, dict) or source.get('path') != BROWSER_SOURCE_ARCHIVE:
        raise ValueError('Expected browser source archive receipt')
    verify(source, source['path'])
    with zipfile.ZipFile(io.BytesIO((destination / source['path']).read_bytes())) as archive:
        archived = {}
        for entry in archive.infolist():
            name = safe_name(entry.filename.rstrip('/') if entry.is_dir() else entry.filename)
            if stat.S_ISLNK(entry.external_attr >> 16):
                raise ValueError('Unsafe browser source archive entry')
            if entry.is_dir():
                continue
            if name in archived:
                raise ValueError('Duplicate browser source archive entry')
            archived[name] = archive.read(entry)
        if archived.keys() != original.keys():
            raise ValueError('Browser source archive differs from its original input list')
        for name, record in original.items():
            if len(archived[name]) != record['bytes'] or digest(archived[name]) != record['sha256']:
                raise ValueError(f'Browser source archive mismatch: {name}')

    def original_copy(name, source_name):
        source_name = safe_name(source_name)
        if source_name not in original:
            raise ValueError(f'Missing original source receipt: {source_name}')
        verify(original[source_name], name)

    copies = {
        **DECLARATION_SOURCES, **RHYTHM_SOURCES,
        'LICENSE': 'LICENSE', 'tetorica_fm2608_synth.webp': 'docs/tetorica_fm2608_synth.webp',
        'generated/ym2608_wasm.js': 'tetorica_src/runtime/generated/ym2608_wasm.js',
        'js/native_audio_effect.wasm': 'tetorica_src/runtime/generated/effects/gain.wasm',
        'licenses/ymfm/LICENSE': 'third_party/tetorica-soundchip-native/vendor/ymfm/LICENSE',
        'licenses/tetorica-virtual-files/LICENSE': 'packages/virtual-files/LICENSE',
        'playground/vendor/fflate-LICENSE': 'docs/playground/vendor/fflate-LICENSE',
    }
    for name, source_name in copies.items():
        original_copy(name, source_name)
    for name in hashes:
        if (not name.startswith(('sources/', 'licenses/'))
                and name.endswith(('.js', '.mjs', '.css', '.d.ts'))
                and name not in modules and name not in copies):
            raise ValueError(f'Unrecorded browser module: {name}')
    for name in EFFECT_INPUTS:
        original_copy('sources/code-effects/' + name, name)
    for name in ('generated/ym2608_wasm.wasm', 'js/native_audio_effect.wasm'):
        if (destination / name).read_bytes()[:8] != b'\0asm\1\0\0\0':
            raise ValueError(f'Invalid WASM header: {name}')

    native = read_json('sources/YM2608.json')
    if (not isinstance(native, dict) or type(native.get('schemaVersion')) is not int
            or native['schemaVersion'] != 1 or native.get('component') != 'ym2608'):
        raise ValueError('Expected YM2608 native source receipt')
    native_inputs = records(native.get('inputs'), 'YM2608 native input')
    native_root = 'sources/ym2608-sdk/'
    if not {native_root + name for name in NATIVE_REQUIRED} <= native_inputs.keys():
        raise ValueError('Incomplete YM2608 native rebuild inputs')
    for name, record in native_inputs.items():
        if not name.startswith(native_root):
            raise ValueError(f'Expected YM2608 SDK source path: {name}')
        verify(record, name)
        relative = name[len(native_root):]
        original_copy(name, 'third_party/soundchip-sdk.json' if relative == 'soundchip-sdk.json'
                      else 'third_party/tetorica-soundchip-native/' + relative)
    pin = read_json(native_root + 'soundchip-sdk.json')
    if (not isinstance(pin, dict) or native.get('sdk') != pin
            or not valid_hash(pin.get('manifestSha256'))):
        raise ValueError('YM2608 SDK pin differs from native receipt')
    if hashes[native_root + 'RELEASE-MANIFEST.json'] != pin['manifestSha256']:
        raise ValueError('YM2608 SDK manifest hash differs from its pin')
    manifest = read_json(native_root + 'RELEASE-MANIFEST.json')
    sdk_files = manifest.get('files') if isinstance(manifest, dict) else None
    if not isinstance(sdk_files, dict):
        raise ValueError('Expected YM2608 SDK file manifest')
    for name, record in native_inputs.items():
        relative = name[len(native_root):]
        if relative in ('RELEASE-MANIFEST.json', 'soundchip-sdk.json'):
            continue
        expected = sdk_files.get(relative)
        if (not isinstance(expected, dict) or expected.get('size') != record['bytes']
                or expected.get('sha256') != record['sha256']):
            raise ValueError(f'YM2608 SDK source differs from its manifest: {relative}')
    build = native.get('build')
    if not isinstance(build, dict) or build.get('id') != 'ym2608':
        raise ValueError('Expected YM2608 compiled build receipt')
    compiled_inputs = build_records(build.get('sourceFiles'), 'YM2608 compiled input')
    if not NATIVE_REQUIRED - {'vendor/ymfm/LICENSE'} <= compiled_inputs.keys():
        raise ValueError('Incomplete YM2608 compiled input receipt')
    for record in compiled_inputs.values():
        name = native_root + record['path']
        if not same_record(record, native_inputs.get(name)):
            raise ValueError(f'YM2608 compiled input differs from its source: {name}')
    outputs = build_records(build.get('outputs'), 'YM2608 compiled output')
    generated = native.get('generated')
    if not isinstance(generated, dict):
        raise ValueError('Expected YM2608 generated output records')
    for name in ('ym2608_wasm.js', 'ym2608_wasm.wasm'):
        verify(generated.get(name), 'generated/' + name)
        if not same_record(generated[name], outputs.get(name)):
            raise ValueError(f'YM2608 generated output differs from its build receipt: {name}')
    if browser.get('sourceCheck') != {'inputs': len(native_inputs), 'sdkVersion': pin.get('version')}:
        raise ValueError('Browser and native YM2608 source checks differ')



def unpack(archive, destination):
    hashes = {}
    with zipfile.ZipFile(archive) as source:
        entries = source.infolist()
        for entry in entries:
            safe_name(entry.filename.rstrip('/') if entry.is_dir() else entry.filename)
            if stat.S_ISLNK(entry.external_attr >> 16):
                raise ValueError(f'Unsafe ZIP entry: {entry.filename}')
        for entry in entries:
            if entry.is_dir():
                continue
            name = str(PurePosixPath(entry.filename))
            if name in hashes:
                raise ValueError(f'Duplicate ZIP entry: {name}')
            data = source.read(entry)
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            hashes[name] = digest(data)
    validate_release(destination, hashes)
    return hashes


LOCAL_REQUIRED = {'index.html', 'synth-fm2608/synth.js'}
LOCAL_MANIFEST = 'local-changes.json'


def safe_name(name):
    if not isinstance(name, str) or not name or any(ord(char) < 32 or ord(char) == 127 for char in name):
        raise ValueError('Expected a safe relative release file path')
    path = PurePosixPath(name)
    if (path.is_absolute() or name != path.as_posix() or '..' in path.parts
            or name == '.' or '\\' in name or ':' in name):
        raise ValueError(f'Unsafe local change path: {name}')
    return name


def valid_hash(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def snapshot_dist(root):
    directory = root / 'dist'
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError('Expected a real dist directory')
    hashes = {}
    for path in sorted(directory.rglob('*')):
        if path.is_symlink():
            raise ValueError(f'Symlinks are not release files: {path.relative_to(directory)}')
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError(f'Expected a regular release file: {path.relative_to(directory)}')
        name = safe_name(path.relative_to(directory).as_posix())
        hashes[name] = digest(path.read_bytes())
    return hashes


def baseline_files(lock):
    files = lock.get('files') if isinstance(lock, dict) else None
    if not isinstance(files, dict) or not valid_hash(lock.get('sha256')):
        raise ValueError('Expected a pinned release SHA-256 and file hashes')
    for name, sha in files.items():
        safe_name(name)
        if not valid_hash(sha):
            raise ValueError(f'Invalid imported file SHA-256: {name}')
    return files


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'Duplicate local manifest property: {key}')
        result[key] = value
    return result


def local_changes(root, lock):
    path = root / LOCAL_MANIFEST
    if path.is_symlink():
        raise ValueError('Local change manifest must not be a symlink')
    if not path.exists():
        return None
    baseline = baseline_files(lock)
    manifest = json.loads(path.read_text(), object_pairs_hook=unique_object)
    if (not isinstance(manifest, dict) or set(manifest) != {'schemaVersion', 'baseSha256', 'files'}
            or type(manifest['schemaVersion']) is not int or manifest['schemaVersion'] != 1
            or not isinstance(manifest['files'], dict)):
        raise ValueError('Invalid local change manifest schema')
    if manifest['baseSha256'] != lock['sha256']:
        raise ValueError('Local changes belong to a different imported release; import and reapply edits')
    for name, sha in manifest['files'].items():
        safe_name(name)
        if sha is None:
            if name not in baseline:
                raise ValueError(f'Cannot delete an unknown imported file: {name}')
        elif not valid_hash(sha):
            raise ValueError(f'Invalid local file SHA-256: {name}')
    return manifest


def require_entries(files):
    missing = LOCAL_REQUIRED - files.keys()
    if missing:
        raise ValueError('Local edits must keep application entry files: ' + ', '.join(sorted(missing)))


def record_local_changes(root):
    lock = json.loads((root / 'release.lock.json').read_text())
    baseline = baseline_files(lock)
    local_changes(root, lock)  # Reject stale or malformed records before replacing them.
    actual = snapshot_dist(root)
    require_entries(actual)
    changes = {name: actual.get(name) for name in sorted(baseline.keys() | actual.keys())
               if actual.get(name) != baseline.get(name)}
    manifest = {'schemaVersion': 1, 'baseSha256': lock['sha256'], 'files': changes}
    destination = root / LOCAL_MANIFEST
    if changes:
        with tempfile.TemporaryDirectory(prefix='.local-edits-', dir=root) as temporary:
            staging = Path(temporary) / LOCAL_MANIFEST
            staging.write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
            staging.replace(destination)
        print(f"Recorded {len(changes)} local changes over Synth {lock['version']}; imported release hashes kept")
    else:
        destination.unlink(missing_ok=True)
        print(f"Restored imported Synth {lock['version']}; no local changes")
    return manifest


def check(root):
    lock = json.loads((root / 'release.lock.json').read_text())
    actual = snapshot_dist(root)
    manifest = local_changes(root, lock)
    expected = dict(lock['files'])
    if manifest is not None:
        for name, sha in manifest['files'].items():
            if sha is None:
                expected.pop(name)
            else:
                expected[name] = sha
        require_entries(actual)
    if actual != expected:
        raise ValueError('dist has unrecorded changes; run npm run record:edits or import the pinned ZIP again')
    return lock


def prepare_app_version(root, version):
    """Load this checkout's standalone metadata updater only when requested."""
    spec = importlib.util.spec_from_file_location(
        'tetorica_app_version', Path(__file__).with_name('app_version.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.prepare_version_update(root, version)


def import_release(root, archive, version=None):
    version_update = prepare_app_version(root, version) if version is not None else None
    if not archive.is_file():
        raise FileNotFoundError(f'Synth release ZIP not found: {archive}')
    sha = digest(archive.read_bytes())
    previous = root / 'release.lock.json'
    old_lock_bytes = previous.read_bytes() if previous.exists() else None
    old_lock = json.loads(old_lock_bytes) if old_lock_bytes is not None else {}
    local_manifest = root / LOCAL_MANIFEST
    old_local_bytes = local_manifest.read_bytes() if local_manifest.exists() else None
    release_version = old_lock.get('version') if old_lock.get('sha256') == sha else f'sha256-{sha[:12]}'
    with tempfile.TemporaryDirectory(prefix='.import-', dir=root) as temporary:
        staging = Path(temporary) / 'dist'
        staging.mkdir()
        hashes = unpack(archive, staging)
        if old_lock.get('sha256') != sha:
            browser = json.loads((staging / BROWSER_RECEIPT).read_text())
            released_version = browser.get('version')
            if isinstance(released_version, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._+-]{0,79}', released_version):
                release_version = released_version
        lock = {'version': release_version, 'archive': archive.name, 'sha256': sha, 'files': hashes}
        destination = root / 'dist'
        backup = Path(temporary) / 'previous-dist'
        installed = False
        try:
            if destination.exists():
                destination.rename(backup)
            staging.rename(destination)
            installed = True
            previous.write_text(json.dumps(lock, indent=2, sort_keys=True) + '\n')
            local_manifest.unlink(missing_ok=True)
            if version_update is not None:
                version_update.apply()
        except BaseException:
            # Metadata applies transactionally too. Restore the imported assets
            # and provenance if either installation or the app update fails.
            if installed:
                shutil.rmtree(destination)
            if backup.exists():
                backup.rename(destination)
            if old_lock_bytes is None:
                previous.unlink(missing_ok=True)
            else:
                previous.write_bytes(old_lock_bytes)
            if old_local_bytes is None:
                local_manifest.unlink(missing_ok=True)
            else:
                local_manifest.write_bytes(old_local_bytes)
            raise
    print(f'Imported {release_version}: {len(hashes)} files, SHA256 {sha}')
    if version_update is not None:
        print(f'App version set to {version_update.version}')
    return lock


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('zip', nargs='?', type=Path, help='Path to the Synth release ZIP')
    parser.add_argument('--version', help='Set the app version to X.Y.Z; independent of the ZIP filename')
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument('--check', action='store_true')
    actions.add_argument('--record-local-changes', action='store_true')
    args = parser.parse_args()
    if (args.check or args.record_local_changes) and (args.zip is not None or args.version is not None):
        parser.error('choose a ZIP import, --check, or --record-local-changes')
    if not args.check and not args.record_local_changes and args.zip is None:
        parser.error('provide the ZIP path: npm run import:release -- ./xxx.zip')
    try:
        if args.check:
            lock = check(ROOT)
            manifest = local_changes(ROOT, lock)
            if manifest is None:
                print(f"Verified Synth {lock['version']}: {len(lock['files'])} files")
            else:
                print(f"Verified locally edited Synth {lock['version']}: {len(manifest['files'])} recorded local changes over SHA256 {lock['sha256']}")
        elif args.record_local_changes:
            record_local_changes(ROOT)
        else:
            import_release(ROOT, args.zip, version=args.version)
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()
