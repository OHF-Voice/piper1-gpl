# Changelog

## Unreleased

- Add Thai phonemizer using TLTK in the new `th` extra
    - `--data.phoneme_type thai` for training; `"phoneme_type": "thai"` in a voice config for synthesis
    - espeak-ng's Thai voice is a placeholder: its `th_dict` holds no lexicon, so unspaced Thai is never segmented; the leading vowels เ แ โ ใ ไ are not reordered; and a tone mark deletes the syllable's vowel, collapsing ป่า/ป้า/ป๊า/ป๋า to the same phonemes
    - TLTK does dictionary-based word segmentation and emits a tone digit (1-5) per syllable, in the same style `phonemize_chinese` uses for Mandarin tones
    - The whole inventory already has ids in the default IPA map, so Thai voices stay compatible with the IPA-based (espeak) warmstart
- Add `script/setup --th`, and install the `th` extra in CI so the Thai tests run

## 1.7.0

- Add Japanese phonemizer using OpenJTalk (`pyopenjtalk-plus`) in the new `ja` extra
    - `--data.phoneme_type japanese` for training; `"phoneme_type": "japanese"` in a voice config for synthesis
    - espeak-ng has no kanji coverage (it reads out Unicode character names) and no pitch accent
    - Full-context labels are parsed for pitch accent and mapped to IPA, so Japanese voices stay compatible with the IPA-based (espeak) warmstart
- Add `script/setup --ja`, and install the `ja` extra in CI so the Japanese tests run
- `libpiper`: add `piper_create_options` and `piper_create_with_options()`, with `piper_create()` kept as a wrapper for ABI compatibility

## 1.6.1

- Run the g2pW model through `piper.g2pw_onnx` instead of `g2pw.api`, dropping `torch` (~750 MB installed) and `requests` from the `zh` extra
    - `g2pw.api` imports torch only to build padded tensors and iterate batches; the model itself already ran under onnxruntime
    - Also 1.5-2x faster, since it no longer forks DataLoader worker processes on every call
    - `g2pW` is still required, for its pinyin/bopomofo lookup tables

## 1.6.0

- Add Hebrew phonemizer using Nakdimon

## 1.5.0

- Add `libpiper` C++ CLI executable ported from the legacy Piper repository, plus a C++ test suite
- Fix `libpiper` builds on Windows (MSVC, MSYS2-GCC) and Windows CI
- Bump embedded espeak-ng version
- Add default speaker id for multi-speaker voices
- Add vowel clustering support (`--data.vowel_clusters`)
- Add in-memory patching for alignments
- Training: add MRD (Multi-Resolution STFT) discriminator, loss/MOS tracking with UTMOS, silence-trim fixes, and dataloader performance improvements
- Pass custom phoneme id map when training

## 1.4.2

- Fix `pathvalidate` dependency

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
