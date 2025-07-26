# Changelog

## 1.3.5-termux

- Termux build improvements and unified CMakeLists.txt

## 1.3.0

- Moved development to OHF-Voice org
- Removed C++ code for now to focus on Python development
    - A C API `libpiper` written in C++ is planned
- Embed espeak-ng directly instead of using separate `piper-phonemize` library
- Change license to GPLv3
- Use Python stable ABI (3.9+) so only a single wheel per platform is needed
- Change Python API:
    - `PiperVoice.synthesize` takes a `SynthesisConfig` and generates `AudioChunk` objects
    - `PiperVoice.synthesize_raw` is removed
- Add seperate `piper.download_voices` utility for downloading voices from HuggingFace
- Allow text as CLI argument: `piper ... -- "Text to speak"`
- Allow text from one or more files with `--input-file <FILE>`
- Excluding any file output arguments will play audio directly with `ffplay`
- Support for raw phonemes in text with `[[ <phonemes> ]]`
- Adjust output volume with `--volume <MULTIPLIER>` (default is 1.0)