# 🐍 Python API

Install with:

``` sh
pip install piper-tts
```

Download a voice, for example:

``` sh
python3 -m piper.download_voices en_US-lessac-medium
```

Use `PiperVoice.synthesize_wav`:

``` python
import wave
from piper import PiperVoice

voice = PiperVoice.load("/path/to/en_US-lessac-medium.onnx")
with wave.open("test.wav", "wb") as wav_file:
    voice.synthesize_wav("Welcome to the world of speech synthesis!", wav_file)
```

Adjust synthesis:

``` python
syn_config = SynthesisConfig(
    volume=0.5,  # half as loud
    length_scale=2.0,  # twice as slow
    noise_scale=1.0,  # more audio variation
    noise_w_scale=1.0,  # more speaking variation
    normalize_audio=False, # use raw audio from voice
    sentence_silence=0.5, # half second pause between sentences
)

voice.synthesize_wav(..., syn_config=syn_config)
```

To use CUDA for GPU acceleration:

``` python
voice = PiperVoice.load(..., use_cuda=True)
```

This requires the `onnxruntime-gpu` package to be installed.

For streaming continuous audio with sentence pauses, use `PiperVoice.synthesize_stream_raw`:

``` python
for pcm_bytes in voice.synthesize_stream_raw("Sentence one. Sentence two.", syn_config=syn_config):
    audio_stream.write(pcm_bytes)
```

For sentence-by-sentence chunks with phonemes and alignments, use `PiperVoice.synthesize`:

``` python
for chunk in voice.synthesize("..."):
    set_audio_format(chunk.sample_rate, chunk.sample_width, chunk.sample_channels)
    write_raw_data(chunk.audio_int16_bytes)
```
