# Code software effects

The original Tetorica effect rack uses BSD-3-Clause and is applied after the
YM2608. The browser implementation is js/native_fx_rack.js and its binary is
js/native_audio_effect.wasm. Rebuild from this directory with Emscripten:

```sh
sh scripts/build_native_audio_effect.sh /tmp/tetorica-fm2608-effects
cp /tmp/tetorica-fm2608-effects/gain.wasm ../../js/native_audio_effect.wasm
```
