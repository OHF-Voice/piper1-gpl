# Changelog

## Unreleased

- Write a valid, empty WAV file when the text has nothing to speak
    - `PiperVoice.synthesize_wav`, the `piper` command and `/synthesize` in `piper.http_server` set the WAV format from the first audio chunk, so empty input left the format unset and closing the file raised `wave.Error: # channels not specified`
    - The format now comes from the voice config before synthesis starts

- Stream audio from `libpiper` for voices split into an encoder and a decoder
    - `piper_synthesize_next` returned one chunk per sentence, so the first sound of a long sentence came only after the whole sentence was synthesized (about 4 seconds for a 6 second sentence of a high voice used by VoiceOver on an Apple M3)
    - `python3 -m piper.split_voice_for_streaming model.onnx` writes `model.encoder.onnx` and `model.decoder.onnx`; when both are next to the model, `piper_create` loads them instead of the full model and the decoder runs in chunks
    - Chunks overlap by more than the decoder's receptive field, so the audio matches the unsplit voice; chunk sizes adapt to the measured decoder speed to keep playback gapless
    - The first sound now comes after about 0.2 seconds regardless of the sentence length
    - Split fp16 voices work too: the latent is converted to float16 when the decoder expects it
- Run `libpiper` inference on several threads
    - The onnxruntime session used a single intra-op thread, which made synthesis about three times slower than the Python API on the same machine
    - It now uses the number of performance cores on Apple platforms and half of the hardware threads elsewhere, at most 4

- Phonemize Hebrew with `HebrewPhonemizer` in `piper.train.infer_torch`
    - The dispatch had no `HEBREW` branch, so a Hebrew checkpoint was inferred from raw espeak-ng output with no error
    - The espeak-ng fallback in `infer_torch` and in the training dataset now raises `ValueError` for any phoneme type other than `espeak`, as `PiperVoice.phonemize` already does, so a type without its own branch fails instead of training or inferring on the wrong phonemes
- Fix training failing on a clip shorter than `segment_size` (#155)
    - A clip that ends up shorter than `segment_size` (8192 samples) after VAD trimming makes the generator produce fewer samples than the reference slice, which the collate function pads to `segment_size`; when every clip in a batch is that short (always with `--data.batch_size 1`), the discriminator feature loss failed with `The size of tensor a (8192) must match the size of tensor b (7424)`
    - The generated and reference audio are now both trimmed to the shorter of the two before the discriminators, so the clip trains on its real content
    - A clip shorter than the STFT window (1024 samples) still cannot be trained on
- Add synthesis settings and a speaker picker to the web page of `piper.http_server`
    - `/synthesize` has always accepted `length_scale`, `noise_scale`, `noise_w_scale`, and `speaker`/`speaker_id`, but the page sent nothing but `text`, so the only way to hear a voice's other speakers or a different speaking rate was to leave the browser and use `curl`
    - The page now has a **Settings** section with a slider and a number box per scale, plus a speaker drop-down for multi-speaker voices; **Reset to voice defaults** restores the starting values
    - The settings start at the voice's defaults and survive each synthesis - only the first `/info` fetch loads them, so the values a user picked are not thrown away when the page refreshes the alignment timeline
    - Emptying a number box drops that field from the request rather than sending `NaN`, so the server falls back to its own default
- Report the speakers and default synthesis settings of the current voice from `/info`
    - The page needs them to populate its new controls, and nothing else exposed them: `/voices` has the whole config of every downloaded voice, but not which voice the server is serving or what `--length-scale` and friends were set to on the command line
    - `voice.speakers` lists `{"id", "name"}` ordered by id, naming speakers the voice does not name itself (`speaker_id_map` is empty on some multi-speaker voices) as `Speaker <id>`
    - `voice.defaults` gives the `speaker_id`/`length_scale`/`noise_scale`/`noise_w_scale` a request gets when it leaves them out, with the command-line arguments applied over the voice config
- Fix `/synthesize` accepting a speaker id one past the last speaker
    - The bounds check was `speaker_id > num_speakers`, so an id equal to `num_speakers` passed through to onnxruntime; negative ids were not checked at all
    - Out-of-range ids now fall back to speaker 0 with a warning, and a `speaker_id` sent as a string is accepted
- Stop warning that speaker `None` was not found
    - Every request to a multi-speaker voice that did not name a speaker logged a "Speaker not found" warning before falling back to the default speaker, which is the documented behavior, not a problem; the warning is now logged only when a `speaker` name was actually given and did not match

- Resolve renamed voices in `piper.download_voices` using the `aliases` list in voices.json
    - A voice that has been renamed keeps its old name in the `aliases` list of its voices.json entry, but nothing honored it: the downloader builds its URL from the voice name alone and never reads voices.json, so every pre-1.0 name (`de-karlsson-low`, `zh-cn-huayan-x-low`, ...) failed - those names do not even match the `<language>-<name>-<quality>` pattern, so they raised before any download was attempted
    - A name that does not parse, or that parses but 404s, is now looked up in the `aliases` lists and downloaded under its current name, with a warning saying what it was renamed to
    - voices.json is only downloaded when a name actually has to be resolved, so a current name still costs the same two requests it always did
- Add Lithuanian phonemizer using espeak-ng plus a pitch accent dictionary
    - `--data.phoneme_type lithuanian` for training; `"phoneme_type": "lithuanian"` in a voice config for synthesis
    - espeak-ng's Lithuanian voice phonemizes well but places stress incorrectly in roughly half of the words, and it cannot express the three Lithuanian pitch accents at all: it collapses them into one primary-stress mark, so kártas ("a time") and kar̃tas ("bitter") come out identical
    - The phonemizer keeps espeak-ng as the phoneme source and moves the stress mark to the accented syllable using a dictionary built from the LIEPA corpus and the g2p-lt-lexicon, both CC-BY-4.0; words that are missing keep espeak-ng's own placement
    - Accents reuse ˈ and ˌ and add ˋ (U+02CB) - one symbol appended to the default IPA map, so Lithuanian voices stay compatible with the IPA-based (espeak) warmstart
    - The stress dictionary (3 MB, CC-BY-4.0) and the letter-name table ship with piper as package data, like the Hebrew model: pip install, download the voice, it works - no extra files and no new dependency; a voice may pass its own files to `LithuanianPhonemizer` instead
    - Lithuanian also has a vocative case spelled like the nominative but accented differently (mamà "mother" vs mãma "mum!"); a dictionary holding one entry per spelling cannot express it, so a short list of nouns that occur as address ships alongside, and a word on that list fenced off by commas is accented on the first syllable
    - The shipped letter-name table also separates z and ž, which espeak-ng names identically (ʑˈee), so the initials of "Zigmas" and "Žygimantas" are no longer read the same, and names Š "šė" rather than "eš"

- Add Japanese phonemization to `libpiper` using OpenJTalk
    - Voices with `"phoneme_type": "japanese"` (e.g. `ja_JP-hi_fi_captain-medium`) could not be used from `libpiper`: the unknown phoneme type threw across the C API and crashed the host application
    - A C++ port of `phonemize_japanese.py` drives the OpenJTalk frontend, built as a pinned static dependency; its output is byte-identical to the Python phonemizer on the golden test sentences
    - The dictionary is not bundled: pass `piper_create_options.openjtalk_dict_dir`, or put it in `<data_dir>/openjtalk`, `<data_dir>` or `<model_dir>/openjtalk`; the new option is guarded by `struct_size`, so existing callers keep working
- Fix `libpiper` corrupting multi-codepoint phonemes in `phoneme_id_map`
    - Keys were reduced to their first codepoint, so diphthongs such as aɪ/aʊ/ɔɪ/eɪ/oʊ folded onto their vowel and every `a` in the text also fed the model the diphthong ids; affected voices, `tl_PH-filipino` among them, produced random sounds instead of speech
    - Multi-codepoint keys now have their own map, and the config's `vowel_clusters` are merged longest-match first before lookup, as in Python; voices without `vowel_clusters` keep the old code path
- Fix the installed `libpiper` CLI on Windows
    - The CLI was installed to `bin` but `piper.dll` and the bundled onnxruntime DLLs to `lib`, so it failed to start outside the build tree (`0xC0000135`); it also looked for the espeak-ng data beside the executable, where the install never put it
    - The runtime DLLs and a copy of the espeak-ng data now go beside the CLI; import libraries stay in `lib` and the data stays in `share` for API callers
- Download `libpiper`'s onnxruntime from Microsoft's NuGet package
    - The release archives `libpiper` downloaded from `github.com/microsoft/onnxruntime` started returning 404 on 2026-11-19, along with the repository itself, so `libpiper` no longer configured on any platform
    - `Microsoft.ML.OnnxRuntime` on nuget.org carries the same 1.22.0 build (the Linux x64 library is byte-identical) for Linux x64/aarch64, macOS x86_64/arm64 and Windows x64, with the headers; the build lays it out like the release archives, under the file names the libraries' install names and sonames refer to
    - The package is checked against a pinned SHA256, and a failed download now stops with `Failed to download <url>` instead of saving the error page and failing later with `Could not find ONNXRUNTIME_LIB`
    - `-DONNXRUNTIME_URL` still takes an archive laid out like the release archives (as the 32-bit ARM build does), and `-DONNXRUNTIME_SHA256` checks it
- Build `libpiper` sources as UTF-8 with MSVC
    - On a Windows machine with a non-UTF-8 code page (e.g. 936), the Chinese phonemizer's UTF-8 punctuation literals were read in the local code page and the build failed
- Build espeak-ng with MSVC 14.52 (Visual Studio 2026), for `libpiper` and for the Python package
    - espeak-ng's compat headers (`unistd.h`, `endian.h`, `getopt.h`) test `#if __has_include_next(...)`, and MSVC has no `__has_include_next`; MSVC 14.44 let it pass, but 14.52 stops with errors C7780 and C1017, so the espeak-ng build failed on current Windows runners
    - Both espeak-ng builds now patch the headers after checkout to define `__has_include_next(header)` as 0 when the compiler lacks it, as espeak-ng itself does since 021e465; the patch is a no-op for GCC and Clang, which define it

- Keep voice files intact when a download is interrupted
    - `urlopen` stops quietly when a connection drops, so a truncated model or config was written to its final path and treated as cached from then on, and `--force-redownload` truncated a working voice before the replacement had arrived
    - Files are now downloaded into a temporary directory inside the destination, checked against `Content-Length`, and moved into place only once every file for the voice has arrived
- Split `[[ raw phonemes ]]` the same way as espeak-ng output
    - Raw phoneme blocks were split into codepoints as typed, so input that looked right did not match what espeak voices were trained on: the ligature `ʤ` has no id and was silently dropped ("stonehenge" became "stone hen"), ASCII `g` and `'` map to ids the model never learned, and neither NFD decomposition nor vowel-cluster merging was applied
    - Raw blocks are now NFD-normalized, ligatures and ASCII lookalikes are replaced with the symbols espeak-ng writes, and vowel clusters are merged
- Fix a use-after-free when more than one espeak-ng phonemizer is created
    - Every `EspeakPhonemizer()` called `espeak_Initialize()` again, which frees and reloads the phoneme tables while the current voice still points into the old ones, so the next phonemization read freed memory; whether that crashed depended on memory layout
    - espeak-ng is now initialized once per data directory, and switching directories terminates it first
- Fix `piper -f -` writing a truncated or empty WAV file to stdout
    - The temporary WAV file was copied to stdout before its writer was closed, so whatever was still buffered was lost and the header kept stale sizes; short single-sentence outputs could come out empty
- Add `requests` to the `th` extra
    - tltk imports `requests` when the package is imported but does not declare it, so a clean `pip install piper-tts[th]` failed at import time
- Include `CMakeLists.txt` and `espeakbridge.c` in the source distribution
    - A wheel built from the sdist was pure Python, with no `espeakbridge` or espeak-ng data, so `EspeakPhonemizer` raised `ImportError` after an install that seemed to succeed
    - CI now builds a wheel from the sdist, installs it and runs the espeak-ng tests against it

- Fix the training learning rate never decaying
    - `VitsModel` sets `automatic_optimization = False`, and under manual optimization Lightning does not step the schedulers returned by `configure_optimizers` — nothing else did either, so the learning rate stayed pinned at its initial value for the whole run
    - Every checkpoint written before this reports `lr_schedulers` `last_epoch=0` no matter how many epochs it trained
    - `on_train_epoch_end` now steps both schedulers, and logs `lr_g`/`lr_d`
- Derive `--model.lr_decay`/`--model.lr_decay_d` from `--trainer.max_epochs` when they are not set explicitly
    - The old default (`0.999875`, from upstream VITS) assumes a ~20,000-epoch schedule and decays the learning rate by only ~1% per 100 epochs, so simply stepping the scheduler would have changed almost nothing
    - The derived decay anneals to `--model.lr_final_ratio` (default `0.05`) of the initial learning rate over the run; `--model.lr_final_ratio 1.0` keeps it constant
    - Open-ended runs (`max_epochs=-1`, the default) have no run length to anneal over and still fall back to the upstream constants, with a warning
    - Resuming with `--ckpt_path` re-asserts the configured decay: `ExponentialLR.state_dict()` carries `gamma`, so the restored value would otherwise silently replace it
- Fix a resume silently reverting to the warmstart checkpoint
    - `LightningCLI._parse_ckpt_path` merges a resumed checkpoint's saved `hyper_parameters` back over the parsed config, so `--model.warmstart_ckpt` comes back even when it is absent from the command line
    - Trainer restores model weights before `on_fit_start` and the optimizer/loop state after it, so the warmstart overwrote the resumed weights with the base model while keeping the restored epoch — discarding every epoch trained so far
    - `on_fit_start` now skips both warmstart paths whenever `trainer.ckpt_path` is set, and logs that it did
- Fix exporting a checkpoint to ONNX with torch 2.9 or newer
    - torch 2.9 made the dynamo-based exporter the default for `torch.onnx.export`; it needs `onnxscript`, which Piper does not install, and it cannot trace `infer()`, whose output length depends on the predicted durations, so `python3 -m piper.train.export_onnx` failed (`GuardOnDataDependentSymNode`)
    - The export now asks for the TorchScript exporter explicitly, and the `train` extra requires torch 2.5 or newer, the first version with that option
- Add `script/libritts_r_to_csv`, which converts extracted LibriTTS-R splits to Piper's metadata CSV
    - Writes through `csv.writer(delimiter="|")` so quoting round-trips through the `csv.reader` the trainer uses — a hand-rolled `"|".join()` silently drops the quotation marks that LibriTTS dialogue is full of
    - Falls back from `.normalized.txt` to the chapter `.trans.tsv` to `.original.txt`, and skips utterances whose audio has no transcript
    - Optional `--min-seconds`/`--max-seconds` filtering and a `--stats` duration histogram
- Save `last.ckpt` every epoch, not only after a top-k save
    - `last.ckpt` came from `save_last` on the `val_mel` checkpoint callback, and Lightning 2.6 writes it only when that callback has just saved a top-k checkpoint, so once `val_mel` stopped improving `last.ckpt` froze and the remaining epochs - the end of the learning rate anneal - were never saved anywhere
    - Measured: a 2,000-epoch run's `last.ckpt` was byte-identical to its epoch 1953 checkpoint
    - `last.ckpt` now has its own callback and is rewritten at the end of every epoch; the `val_mel` and `val_mos` top-5 checkpoints are unchanged, and runs started under the old callbacks resume cleanly
- Start missing speaker conditioning at zero when warmstarting a multi-speaker voice from a single-speaker base
    - The base has no speaker conditioning, so the projections that add the speaker embedding into the posterior encoder, flows, decoder and duration predictor came up at random and were added straight onto activations the copied weights were trained without; the model did not start from the base
    - The scale and bias of each missing conditioning projection are now zeroed, so every speaker starts out reproducing the base exactly and still gets gradient from the first step; a base that already has speaker conditioning is copied as before
- Fix a segfault in `monotonic_align` during training
    - The backward loop of `maximum_path_each` read `value[y-1, ...]` at `y == 0`, which is out of bounds with wraparound disabled
- Stop the training step from waiting on the GPU once per utterance
    - `slice_segments` turned a GPU offset into a Python int for every utterance, three times per step; it is now one gather, and the random offsets, the discriminator losses and the duration predictor's noise stay on the device
    - Host syncs per step drop from 318 to 155 at batch size 16, about 2% faster on an RTX 3090; the gather is bit-identical to the old loop
- Make vocoder and duration-predictor underfitting visible
    - `val_mel` is an L1 over the same ~0.37 s window the decoder trains on, so it cannot show a vocoder that saw too few passes over the audio; a base model trained on 290 h finished its whole anneal audibly underfit with nothing in the logs
    - `val_vocoder_mel` is the teacher-forced decoder error over whole validation utterances, so it moves with vocoder fit alone
    - Vocoder coverage, in passes over the training audio, is reported when training starts, with a warning below ~150 passes
    - `iters` logs the number of batches actually seen; Lightning's `global_step`, also used in checkpoint filenames, counts two optimizer steps per batch
    - `gin_channels > 0` with `num_speakers <= 1` now raises, since that conditioning (~24% of the generator) could never be used
    - Optional `--data.length_bucketing` groups utterances of similar length into batches, cutting padding from ~61% to ~3% on a corpus with a long tail; it is off by default because it changes batch composition
- Tag validation audio in TensorBoard by position (`val/00`, `val/01`, ...) instead of by transcript
    - Transcripts with quotes, question marks or ampersands broke the key the dashboard fetches each clip by, so those clips showed as zero length; identical transcripts overwrote each other, and the tags changed whenever a run was resumed
    - The transcript moves to the text dashboard under the same tag
- Write per-phoneme training counts into voice configs as `phoneme_counts`
    - `prepare_data` counts how often each phoneme occurs in the cached phoneme ids, so a voice records which symbols of its id map it was actually trained on; phonemes that never occur are left out, and so are PAD/BOS/EOS
    - Phonemes that share an id, like `。` and `.` in the Chinese map, each get that id's count
    - `python3 -m piper.train.phoneme_counts` backfills the counts into the config of a voice trained before this, keeping keys it does not know
    - Also fix the dataset's missing-file checks, which tested a `Path`'s truthiness (always true) instead of whether the file exists
- Document how long to train, how to read `val_mos`, and how to choose a checkpoint in `docs/TRAINING.md`
    - Starting points from measured runs, counted in epochs: about 2,000 for fine-tunes on under ~5 h of audio, 650-850 for ~10-15 h
    - `--ckpt_path` resumes the checkpoint's epoch counter and hyperparameters, so a fine-tune from lessac medium (epoch 2164, `lr_decay` 0.999875) runs at a nearly constant learning rate; `--model.warmstart_ckpt` does not
    - `val_mos` moves by 0.1-0.15 from epoch to epoch, reads lower for non-English voices, and does not hear pronunciation

- Document voice licensing and commercial use
    - `docs/LICENSING.md` explains how to read a voice's model card and follow its fine-tuning chain, why lessac-derived voices are restricted, and the two bases (rdh and hifi_tts_92) that voices are now retrained from
    - `docs/COMMERCIAL_USE.md` lists the voices whose whole training chain uses recordings licensed for commercial use, what each license asks of you, and which voices are left out and why

## 1.8.0

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
