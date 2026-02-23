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
)

voice.synthesize_wav(..., syn_config=syn_config)
```

To use CUDA for GPU acceleration:

``` python
voice = PiperVoice.load(..., use_cuda=True)
```

This requires the `onnxruntime-gpu` package to be installed.

For streaming, use `PiperVoice.synthesize`:

``` python
for chunk in voice.synthesize("..."):
    set_audio_format(chunk.sample_rate, chunk.sample_width, chunk.sample_channels)
    write_raw_data(chunk.audio_int16_bytes)
```

For input streaming (e.g. from an LLM), use `PiperVoice.synthesize_stream`:

``` python
import sys
from piper import PiperVoice

voice = PiperVoice.load("/path/to/en_US-lessac-medium.onnx")

# Feed text incrementally; audio is yielded as soon as
# a complete sentence is detected.
for chunk in voice.synthesize_stream(sys.stdin):
    write_raw_data(chunk.audio_int16_bytes)
```

`synthesize_stream` accepts any `Iterable[str]` — a file, a generator
yielding lines from a network stream, or any other source of text
chunks.  The voice model is loaded once; only phonemization and
inference run per sentence.
