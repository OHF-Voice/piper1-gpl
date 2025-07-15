# 🖥️ Command Line Interface

The Piper command-line interface allows for quickly getting audio from text and trying out different voices. It can be slow, however, because it needs to load the voice model each time. For repeated use, the [web server](API_HTTP.md) is recommended.

## Installing

Install with:

``` sh
pip install piper-tts
```

## Downloading Voices

List voices with:

``` sh
python3 -m piper.download_voices
```

Choose a voice ([samples here][samples]) and download. For example:

``` sh
python3 -m piper.download_voices en_US-lessac-medium
```

This will download to the current directory. Override with `--data-dir <DIR>`

## Running

After downloading the example voice above, run:

``` sh
python3 -m piper -m en_US-lessac-medium -f test.wav -- 'This is a test.'
```

This will write `test.wav` with the sentence "This is a test."
If you have voices in a different directory, use `--data-dir <DIR>`

If you have [ffplay][] installed, omit `-f` to hear the audio immediately:

``` sh
python3 -m piper -m en_US-lessac-medium -- 'This will play on your speakers.'
```

Running Piper this way is slow since it needs to load the model each time. Run the [web server](API_HTTP.md) unless you need to stream audio (see `--output-raw` from `--help`).

Some other useful command-line options:

* `--cuda` - enable GPU acceleration (requires `onnxruntime-gpu` package)
* `--input-file` - read input text from one or more files
* `--sentence-silence` - add seconds of silence to all but the last sentence
* `--volume` - adjust volume multiplier (default: 1.0)
* `--no-normalize` - disable automatic volume normalization

### Raw Phonemes

You can inject raw espeak-ng phonemes with `[[ <phonemes> ]]` blocks. For example:

```
I am the [[ bˈætmæn ]] not [[bɹˈuːs wˈe‍ɪn]]
```

To get phonemes from espeak-ng, use:

``` sh
espeak-ng -v <VOICE> --ipa=3 -q <TEXT>
```

For example:

``` sh
espeak-ng -v en-us --ipa=3 -q batman
bˈætmæn
```

## Binary Releases

* [amd64](https://github.com/rhasspy/piper/releases/download/v1.2.0/piper_amd64.tar.gz) (64-bit desktop Linux)
* [arm64](https://github.com/rhasspy/piper/releases/download/v1.2.0/piper_arm64.tar.gz) (64-bit Raspberry Pi 4)
* [armv7](https://github.com/rhasspy/piper/releases/download/v1.2.0/piper_armv7.tar.gz) (32-bit Raspberry Pi 3/4)

<!-- Links -->
[samples]: https://rhasspy.github.io/piper-samples/
[ffplay]: https://ffmpeg.org/ffplay.html
