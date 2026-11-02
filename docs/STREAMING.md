# Streaming

By default, `libpiper` synthesizes a whole sentence before `piper_synthesize_next` returns its audio. For long sentences this means waiting several seconds for the first sound, which is especially noticeable with screen readers.

When a voice is split into an encoder and a decoder, `libpiper` runs the encoder once per sentence and then the decoder in chunks. Each call to `piper_synthesize_next` returns the next chunk, so playback can start after a fraction of a second.

## Splitting Voices

``` sh
python3 -m piper.split_voice_for_streaming /path/to/model.onnx
```

This writes `/path/to/model.encoder.onnx` and `/path/to/model.decoder.onnx`. Like [alignments](ALIGNMENTS.md), it requires the `onnx` Python package (not `onnxruntime`), which is not needed afterwards. Alignment outputs of a patched voice are kept, so patch first if you need both.

`piper_create` uses the split model automatically when both files are next to the model path it is given, and then does not load the full model. Keep `model.onnx` around for other Piper installations.

## Output

Neighbouring chunks overlap by a few latent frames on both sides, more than the decoder's receptive field, so the streamed audio is the same as decoding the sentence at once (up to floating point rounding).

The first chunk of a sentence is small for a fast first sound. Later chunks are sized from the measured decoder speed so that each is ready before the audio returned so far has been played, assuming playback starts with the first chunk.

Phonemes, phoneme ids, and alignments of a sentence are returned with its first chunk.
