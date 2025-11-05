# 🏋️ Training

Code for training new voices is included in `src/piper/train` and can be run with `python3 -m piper.train fit`.
This uses [PyTorch Lightning][lighting] and the `LightningCLI`.

You will need the following system packages installed (`apt-get`):

* `build-essential`
* `cmake`
* `ninja-build`

Then clone the repo and install the training dependencies:

``` sh
git clone https://github.com/OHF-voice/piper1-gpl.git
cd piper1-gpl
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .[train]
```

and then build the cython extension:

``` sh
./build_monotonic_align.sh
```

If you are running from the repo, you will need to do a dev build:

``` sh
python3 setup.py build_ext --inplace
```

To train, you must have a CSV file with `|` as a delimiter and the format:

``` csv
utt1.wav|Text for utterance 1.
utt2.wav|Text for utterance 2.
...
```

The first column is the name of the audio file (any format supported by [librosa][]), which must be located in `--data.audio_dir` (see below).

The second column is the text that will be passed to [espeak-ng][] for phonemization (similar to `espeak-ng --ipa=3`).

Run the training script:

``` sh
python3 -m piper.train fit \
  --data.voice_name "<name of voice>" \
  --data.csv_path /path/to/metadata.csv \
  --data.audio_dir /path/to/audio/ \
  --model.sample_rate 22050 \
  --data.espeak_voice "<espeak voice name>" \
  --data.cache_dir /path/to/cache/dir/ \
  --data.config_path /path/to/write/config.json \
  --data.batch_size 32 \
  --ckpt_path /path/to/finetune.ckpt  # optional but highly recommended
```

where:

* `data.voice_name` is the name of your voice (can be anything)
* `data.csv_path` is the path to the CSV file with audio file names and text
* `data.audio_dir` is the directory containing the audio files (usually `.wav`)
* `model.sample_rate` is the sample rate of the audio in hertz (usually 22050)
* `data.espeak_voice` is the espeak-ng voice/language like `en-us` (see `espeak-ng --voices`)
* `data.cache_dir` is a directory where training artifacts are cached (phonemes, trimmed audio, etc.)
* `data.config_path` is the path to write the voice's JSON config file
* `data.batch_size` is the training batch size
* `ckpt_path` is the path to an existing [Piper checkpoint][piper-checkpoints]

Using `--ckpt_path` is recommended since it will speed up training a lot, even if the checkpoint is from a different language. Only `medium` quality checkpoints are supported without [tweaking other settings][audio-config].

Run `python3 -m piper.train fit --help` for many more options.

## Exporting

When your model is finished training, export it to onnx with:

``` sh
python3 -m piper.train.export_onnx \
  --checkpoint /path/to/checkpoint.ckpt \
  --output-file /path/to/model.onnx
```

To make this compatible with other Piper voices, rename `model.onnx` as `<language>-<name>-medium.onnx` (e.g., `en_US-lessac-medium.onnx`). Name the JSON config file that was written to `--data.config_path` **during training** the same name with a `.json` extension. So you would have two files for the voice:

* `en_US-lessac-medium.onnx` (from the export script)
* `en_US-lessac-medium.onnx.json` (from training)

## Hardware

Most of the Piper voices were trained/fine-tuned on a Threadripper 1900X with 128GB of RAM and either an NVIDIA A6000 (48 GB VRAM) or a 3090 (24 GB VRAM).

Users have reported success with as little as 8GB of VRAM and alternative GPUs like the RX 7600.

<!-- Links -->
[espeak-ng]: https://github.com/espeak-ng/espeak-ng
[lighting]: https://lightning.ai/docs/pytorch/stable/
[librosa]: https://librosa.org/doc/latest/index.html
[piper-checkpoints]: https://huggingface.co/datasets/rhasspy/piper-checkpoints
[audio-config]: https://github.com/rhasspy/piper/blob/9b1c6397698b1da11ad6cca2b318026b628328ec/src/python/piper_train/vits/config.py#L20
