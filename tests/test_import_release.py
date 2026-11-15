"""Readable FM2608 release fixtures exercise import without opening the app."""
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/import_release.py'
spec = importlib.util.spec_from_file_location('fm2608_importer', SCRIPT)
importer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(importer)


def plain(data):
    return {'bytes': len(data), 'sha256': importer.digest(data)}


def source_archive(original):
    enclosed = io.BytesIO()
    with zipfile.ZipFile(enclosed, 'w') as archive:
        for name, data in original.items():
            archive.writestr(name, data)
    return enclosed.getvalue()


def release_files(text=b'readable fixture'):
    files = {name: ('fixture ' + name).encode() for name in importer.REQUIRED}
    files['index.html'] = text
    original = {}
    copies = {
        **importer.DECLARATION_SOURCES, **importer.RHYTHM_SOURCES,
        'LICENSE': 'LICENSE', 'tetorica_fm2608_synth.webp': 'docs/tetorica_fm2608_synth.webp',
        'generated/ym2608_wasm.js': 'tetorica_src/runtime/generated/ym2608_wasm.js',
        'js/native_audio_effect.wasm': 'tetorica_src/runtime/generated/effects/gain.wasm',
        'licenses/ymfm/LICENSE': 'third_party/tetorica-soundchip-native/vendor/ymfm/LICENSE',
        'licenses/tetorica-virtual-files/LICENSE': 'packages/virtual-files/LICENSE',
        'playground/vendor/fflate-LICENSE': 'docs/playground/vendor/fflate-LICENSE',
    }
    files['js/native_audio_effect.wasm'] = b'\0asm\1\0\0\0'
    files['generated/ym2608_wasm.wasm'] = b'\0asm\1\0\0\0'
    for name, source in copies.items():
        original[source] = files[name]
    for name in importer.EFFECT_INPUTS:
        data = original.setdefault(name, ('effect source ' + name).encode())
        files['sources/code-effects/' + name] = data

    native_root = 'sources/ym2608-sdk/'
    source_files = []
    for name in sorted(importer.NATIVE_REQUIRED):
        data = original.setdefault('third_party/tetorica-soundchip-native/' + name,
                                   ('native source ' + name).encode())
        files[native_root + name] = data
        if name != 'vendor/ymfm/LICENSE':
            source_files.append({'path': name, 'size': len(data), 'sha256': importer.digest(data)})
    manifest = {'schemaVersion': 1, 'name': 'tetorica-soundchip-native', 'files': {
        name: {'size': len(files[native_root + name]), 'sha256': importer.digest(files[native_root + name])}
        for name in importer.NATIVE_REQUIRED}}
    files[native_root + 'RELEASE-MANIFEST.json'] = json.dumps(manifest).encode()
    pin = {'schemaVersion': 1, 'version': 'fixture-sdk',
           'manifestSha256': importer.digest(files[native_root + 'RELEASE-MANIFEST.json'])}
    files[native_root + 'soundchip-sdk.json'] = json.dumps(pin).encode()
    original['third_party/tetorica-soundchip-native/RELEASE-MANIFEST.json'] = files[native_root + 'RELEASE-MANIFEST.json']
    original['third_party/soundchip-sdk.json'] = files[native_root + 'soundchip-sdk.json']
    native_inputs = [{'path': name, **plain(data)} for name, data in files.items()
                     if name.startswith(native_root)]
    generated = {name: plain(files['generated/' + name])
                 for name in ('ym2608_wasm.js', 'ym2608_wasm.wasm')}
    files['sources/YM2608.json'] = json.dumps({
        'schemaVersion': 1, 'component': 'ym2608', 'sdk': pin,
        'inputs': native_inputs, 'generated': generated,
        'build': {'id': 'ym2608', 'sourceFiles': source_files, 'outputs': [
            {'path': name, 'size': value['bytes'], 'sha256': value['sha256']}
            for name, value in generated.items()]},
    }).encode()
    module_names = sorted(importer.BROWSER_ENTRIES) + ['js/ym2608synth.js']
    files['js/ym2608synth.js'] = b'export const fixture = true;'
    modules = []
    for name in module_names:
        original['docs/' + name] = files[name]
        dependencies = ['../generated/ym2608_wasm.js'] if name == 'js/ym2608-worklet.js' else []
        if name == 'synth-fm2608/synth.js':
            dependencies = ['../js/ym2608synth.js']
        modules.append({'path': name, 'sourcePath': 'docs/' + name,
                        'localImports': dependencies, **plain(files[name])})
    files[importer.BROWSER_SOURCE_ARCHIVE] = source_archive(original)
    files[importer.BROWSER_RECEIPT] = json.dumps({
        'schemaVersion': 1, 'product': 'Tetorica FM2608 Synth', 'productId': 'tetorica-fm2608-synth',
        'builder': {'name': 'source-copy', 'minify': False, 'bundle': False},
        'bundles': [record for record in modules if record['path'] in importer.BROWSER_ENTRIES],
        'modules': modules, 'originalInputs': [{'path': name, **plain(data)} for name, data in original.items()],
        'sourceArchive': {'path': importer.BROWSER_SOURCE_ARCHIVE, **plain(files[importer.BROWSER_SOURCE_ARCHIVE])},
        'sourceCheck': {'inputs': len(native_inputs), 'sdkVersion': pin['version']},
    }).encode()
    return files


def write_archive(path, files):
    with zipfile.ZipFile(path, 'w') as output:
        for name, data in files.items():
            output.writestr(name, data)


def change_receipt(files, name, change):
    receipt = json.loads(files[name])
    change(receipt)
    files[name] = json.dumps(receipt).encode()


class ImportTests(unittest.TestCase):
    def unpack(self, files):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / 'release.zip'
            write_archive(archive, files)
            return importer.unpack(archive, Path(tmp) / 'out')

    def test_all_original_bytes_and_readable_sources_are_preserved(self):
        files = release_files()
        self.assertEqual(self.unpack(files), {name: importer.digest(data) for name, data in files.items()})

    def test_original_source_native_assets_effects_and_notices_cannot_change(self):
        for name in ['generated/ym2608_wasm.js', 'generated/ym2608_wasm.wasm',
                     'synth-fm2608/synth.js', 'js/ym2608synth.js',
                     'sources/ym2608-sdk/wasm/ym2608_wasm.cpp',
                     'sources/ym2608-sdk/vendor/ymfm/LICENSE',
                     'js/native_audio_effect.wasm',
                     'sources/code-effects/tetorica_src/native/audio_effect/graph.c',
                     'assets/opna-rhythm/generate.mjs', 'js/tetorica_ym2608_adpcm_rom.bin',
                     'licenses/ymfm/LICENSE', *importer.DECLARATION_SOURCES,
                     importer.BROWSER_SOURCE_ARCHIVE]:
            files = release_files(); files[name] = b'changed'
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.unpack(files)

    def test_native_receipt_requires_complete_build_sources_matching_pin_and_outputs(self):
        for change in [
            lambda r: r.update(component='ym2612'),
            lambda r: r.update(inputs=r['inputs'][1:]),
            lambda r: r['sdk'].update(manifestSha256='0' * 64),
            lambda r: r['build']['sourceFiles'][0].update(sha256='0' * 64),
            lambda r: r['build'].update(sourceFiles=None),
            lambda r: r['build']['sourceFiles'].append(None),
            lambda r: r['build'].update(sourceFiles=r['build']['sourceFiles'][1:]),
            lambda r: r['build']['outputs'][0].update(sha256='0' * 64),
            lambda r: r['build'].update(outputs='invalid'),
            lambda r: r['generated']['ym2608_wasm.wasm'].update(sha256='0' * 64),
        ]:
            files = release_files(); change_receipt(files, 'sources/YM2608.json', change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.unpack(files)

    def test_missing_release_inputs_and_original_assets_are_rejected(self):
        for name in [*importer.REQUIRED,
                     'sources/code-effects/tetorica_src/native/audio_effect/graph.c',
                     'sources/ym2608-sdk/wasm/ym2608_wasm.cpp']:
            files = release_files(); del files[name]
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.unpack(files)

    def test_product_identity_and_source_copy_builder_are_required(self):
        for change in [
            lambda r: r.update(productId='tetorica-sid-synth'),
            lambda r: r.update(product='SID Synth'),
            lambda r: r.update(schemaVersion=True),
            lambda r: r.update(builder=None),
            lambda r: r['builder'].update(minify=True),
            lambda r: r['builder'].update(bundle=True),
            lambda r: r['sourceCheck'].update(inputs=0),
        ]:
            files = release_files(); change_receipt(files, importer.BROWSER_RECEIPT, change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.unpack(files)

    def test_module_graph_requires_every_dependency_and_matching_entry(self):
        for change in [
            lambda r: r.update(modules=[m for m in r['modules'] if m['path'] != 'js/ym2608synth.js']),
            lambda r: r['modules'][0].update(sha256='0' * 64),
            lambda r: r['modules'][0].update(localImports=['../../escape.js']),
            lambda r: r.update(bundles=[]),
            lambda r: r.update(modules=[]),
        ]:
            files = release_files(); change_receipt(files, importer.BROWSER_RECEIPT, change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.unpack(files)
        files = release_files(); files['js/extra.js'] = b'// unrecorded'
        with self.assertRaisesRegex(ValueError, 'Unrecorded'):
            self.unpack(files)

    def test_enclosed_source_archive_must_match_the_complete_original_input_list(self):
        for kind in ('changed', 'missing', 'extra', 'unsafe', 'duplicate'):
            files = release_files()
            with zipfile.ZipFile(io.BytesIO(files[importer.BROWSER_SOURCE_ARCHIVE])) as archive:
                original = {name: archive.read(name) for name in archive.namelist()}
            if kind == 'changed': original['docs/synth-fm2608/synth.js'] = b'changed'
            if kind == 'missing': del original['docs/synth-fm2608/synth.js']
            if kind == 'extra': original['extra.js'] = b'extra'
            if kind == 'unsafe': original['../escape.js'] = b'escape'
            enclosed = io.BytesIO(source_archive(original))
            if kind == 'duplicate':
                with zipfile.ZipFile(enclosed, 'a') as archive:
                    with self.assertWarns(UserWarning):
                        archive.writestr('docs/synth-fm2608/synth.js', b'duplicate')
            files[importer.BROWSER_SOURCE_ARCHIVE] = enclosed.getvalue()
            change_receipt(files, importer.BROWSER_RECEIPT,
                           lambda r: r['sourceArchive'].update(plain(enclosed.getvalue())))
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.unpack(files)

    def test_invalid_replacement_leaves_previous_import_and_lock_intact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); archive = root / 'release.zip'
            write_archive(archive, release_files(b'first'))
            first = importer.import_release(root, archive)
            write_archive(archive, {'index.html': b'wrong app'})
            with self.assertRaises(ValueError): importer.import_release(root, archive)
            self.assertEqual(importer.check(root), first)
            self.assertEqual((root / 'dist/index.html').read_bytes(), b'first')

    def test_archive_name_is_independent_of_web_and_app_versions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); archive = root / 'unrelated.zip'
            files = release_files()
            change_receipt(files, importer.BROWSER_RECEIPT, lambda r: r.update(version='web-20261115'))
            write_archive(archive, files)
            first = importer.import_release(root, archive)
            self.assertEqual(first['version'], 'web-20261115')
            self.assertEqual(importer.import_release(root, archive)['version'], first['version'])
            self.assertEqual(importer.check(root), first)

    def test_unsafe_paths_duplicate_names_and_symlinks_are_rejected(self):
        for name in ['../escape', '/absolute', 'a/../../escape', 'a\\escape', 'C:/escape',
                     './index.html', 'a//b', 'a/./b', 'a\nb']:
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.unpack({name: b'bad'})
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); archive = root / 'release.zip'
            with zipfile.ZipFile(archive, 'w') as output:
                output.writestr('index.html', b'a')
                with self.assertWarns(UserWarning): output.writestr('index.html', b'b')
            with self.assertRaisesRegex(ValueError, 'Duplicate'):
                importer.unpack(archive, root / 'out')
            with zipfile.ZipFile(archive, 'w') as output:
                entry = zipfile.ZipInfo('link'); entry.create_system = 3
                entry.external_attr = 0o120777 << 16
                output.writestr(entry, '../../escape')
            with self.assertRaisesRegex(ValueError, 'Unsafe'):
                importer.unpack(archive, root / 'out2')


if __name__ == '__main__':
    unittest.main()
