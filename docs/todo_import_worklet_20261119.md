# FM2608 release Worklet import — 2026-11-19

The 0.1.5 Web ZIP uses `synth-fm2608/audio_worklet.js`, but the Tauri importer
still requires the older `js/ym2608-worklet.js` bundle entry.

- [x] Accept the two explicit complete bundle layouts (legacy shared Worklet
  or current app Worklet); preserve complete module/source/native verification.
- [x] Test both valid layouts and reject missing, ambiguous or changed entries.
- [x] Validate and import the requested 0.1.5 ZIP with app version 0.1.5;
  check the resulting file pin and all app version metadata.

No publishing, signing, tagging or commit is requested. Preserve the parent
repository's already staged Analyzer changes.

Completed:

- Imported `tetorica_fm2608_synth_dev_itch_0.1.5.zip`: 186 original files,
  SHA256 `941fa67a00e927645dac87fde78e9c44357ecefee6cb25e03209de68c4fcc3e7`.
  `import_release.py --check` passes. The Web receipt's `dev` identifier is
  preserved independently from the desktop app version.
- `package.json`, `package-lock.json`, `src-tauri/Cargo.toml`,
  `src-tauri/Cargo.lock` and `src-tauri/tauri.conf.json` all use app version
  `0.1.5`. Dependency versions were not changed.
- All 34 Python tests and 47 Node tests pass. Both explicit Worklet layouts
  retain source-archive, module/dependency, native build and output hash checks.
- The existing desktop browser checker passes Chromium and WebKit with muted
  physical output and a mocked IPC host. Actual WASM/Worklet audio, four sound
  sources, Code, VGM transport, exports and output fallback were exercised.
  This is not a signed application build or a physical CPAL-device test.
