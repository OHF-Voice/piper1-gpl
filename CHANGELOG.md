# Changelog

## 1.4.1

- Add missing wheels

## 1.4.0

- Add Chinese phonemizer based on [g2pW](https://github.com/GitYCC/g2pW/)
    - Using a quantized version of the original model with `quantize_dynamic`
- Add `--data.phoneme_type pinyin` for Chinese phonemization using g2pW
- Add `--data.phoneme_type text` for using IPA phonemes directly (no espeak-ng)
- Add `--model.vocoder_warmstart_ckpt <CHECKPOINT>` to restore vocoder params only
- Add `--data.dataset_type 'phoneme_ids'` to train with pre-generated phoneme ids
    - Use `--data.num_symbols <N>` to set number of phonemes
    - Use `--data.phonemes_path "/path/to/phonemes.json"` for phoneme/id map
- Add `--output-dir-naming` option with `timestamp` (default) and `text`

## 1.3.1

- Add experimental support for alignments (see docs/ALIGNMENTS.md)
- Raw phonemes no longer split sentences
- Fix training for multi-speaker voices

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
- Add separate `piper.download_voices` utility for downloading voices from HuggingFace
- Allow text as CLI argument: `piper ... -- "Text to speak"`
- Allow text from one or more files with `--input-file <FILE>`
- Excluding any file output arguments will play audio directly with `ffplay`
- Support for raw phonemes in text with `[[ <phonemes> ]]`
- Adjust output volume with `--volume <MULTIPLIER>` (default is 1.0)
