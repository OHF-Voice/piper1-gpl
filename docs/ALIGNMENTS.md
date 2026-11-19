# Alignments

Experimental support for audio alignments has been added to Piper's Python and C++ APIs.
This exposes the number of audio samples for each **phoneme id** used during synthesis, and can be used for [aligning speech with mouth movement][visemes].

## Patching Voices

To access alignments, you must first "patch" a voice's ONNX model file:

``` sh
python3 -m piper.patch_voice_with_alignment /path/to/model.onnx
```

This requires the `onnx` Python package to be installed (not to be confused with `onnxruntime`). After patching, the `onnx` package is no longer required. Patched ONNX models should still work fine with existing Piper installations.

### Patching at Load Time

Alternatively, you can patch a voice in memory when loading it, without writing a modified model to disk:

``` python
voice = PiperVoice.load("/path/to/model.onnx", include_alignments=True)
```

This also requires the `onnx` package (install with `pip install piper-tts[alignment]`), but it leaves the original `.onnx` file untouched. If the model is already patched, or the `onnx` package is unavailable, the voice loads normally and alignments are simply unavailable.

## Python API

The `AudioChunk` class has been extended with several new fields:

* `phonemes` - list of phonemes used to produce the audio chunk
* `phoneme_ids` - list of phonemes ids used to produce the audio chunk
* `phoneme_id_samples` - number of audio samples for each phoneme id
* `phoneme_alignments` - list of phoneme/sample count alignments

Both the `phoneme_id_sample` and `phoneme_alignments` fields will be missing if alignments are not supported by the voice model or are disabled with `include_alignments=False`.

## C++ API

The `piper_audio_chunk` struct has been extended with several new fields:

* `phonemes` - array of codepoints whose length is `num_phonemes`
* `phoneme_ids` - array of ids whose length is `num_phoneme_ids`
* `alignments` - array of sample counts whose length is `num_alignments`

The `alignments` array will be empty if the voice doesn't support them, but the `phonemes` and `phonemes_ids` arrays will always be present.

The `phoneme_ids` array contains the ids that were used to synthesize audio for the chunk. It looks like [1, 0, id1, 0, id2, 0, ..., 2] where:

* 0 = pad
* 1 = beginning of sentence
* 2 = end of sentence

Since a single phoneme can produce multiple phoneme ids, the `phonemes` array is a bit more complex. It looks like [p1, p1, 0, p2, p2, 0, ...] where the same phoneme codepoint is repeated for each corresponding id in `phoneme_ids`. A value of 0 separates each phoneme, and in most cases there will be two codepoints per phoneme corresponding to the phoneme id and the pad id.

The `alignments` array contains the number of audio samples for each phoneme id. You can determine which phoneme these belong to by:

1. Read N (repeated) codepoints from `phonemes` until a 0 is reached (or end)
2. The next N phoneme ids correspond to that phoneme
3. The next N alignments (sample counts) correspond to that phoneme
4. Advance your iterators in the `phoneme_ids` and `alignments` arrays by N
5. Repeat

<!-- Links -->
[visemes]: https://github.com/aflorithmic/viseme-to-video
