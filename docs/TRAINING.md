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
python3 -m pip install -e '.[train]'
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

The other column(s) will depend on the [training settings](#settings). By default, the second column is the text that will be passed to [espeak-ng][] for phonemization (similar to `espeak-ng --ipa=3`).

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

Using `--ckpt_path` is recommended since it will speed up training a lot, even if the checkpoint is from a different language. Only `medium` quality checkpoints are supported without [tweaking other settings][audio-config]. See [How Long To Train](#how-long-to-train) for choosing `--trainer.max_epochs`, and how it interacts with `--ckpt_path`.

Run `python3 -m piper.train fit --help` for many more options.

## Settings

Some training settings will change the input data format.

### LibriTTS-R

`script/libritts_r_to_csv` converts extracted [LibriTTS-R][libritts-r] splits
into the multi-speaker CSV below:

``` sh
script/libritts_r_to_csv /path/to/libritts_r -o metadata.csv \
  --min-seconds 0.5 --max-seconds 20
```

It reads `train-clean-100`, `train-clean-360` and `train-other-500` by default
(`--splits` to choose), prefers each utterance's `.normalized.txt` and falls
back to the chapter `.trans.tsv` then `.original.txt`, and skips utterances with
no transcript. It prints the `--data.audio_dir` and `--model.num_speakers` to
train with. `--stats` reports a duration histogram without filtering anything.

### Multiple Speakers

If you have more than one speaker in your dataset, the input CSV format changes to:

``` csv
utt1.wav|speaker_1|Text for utterance 1 with first speaker.
utt2.wav|speaker_2|Text for utterance 2 with second speaker.
...
```

where `speaker_1` and `speaker_2` are the **names** of the speakers. When training begins, Piper will count up the number of unique speaker names and create a mapping between speaker names and ids. This mapping will be saved in the `config.json` file for the voice (`--data.config_path`).

### Custom Phonemes

If you want to skip phonemization with `espeak-ng`, set `--data.phoneme_type text` and use the CSV format:

``` csv
utt1.wav|phonemes_for_utt_1
utt2.wav|phonemes_for_utt_2
...
```

The final column is now the UTF-8 codepoints that you want to be the phonemes for each utterance. In Python, these are converted to a list with:

```python
phonemes_list = list(unicodedata.normalize("NFD", phonemes_text))
```

These phonemes are run through the normal process to create phoneme ids, which includes adding the BOS/EOS ids and interspersing PAD.

### Custom Phoneme Ids

For complete control over phonemization, use `--data.data_type phoneme_ids` and use the CSV format:

``` csv
utt1.wav|Text for utterance 1.|0 1 2 3 4 5
utt2.wav|Text for utterance 2.|5 4 3 2 1 0
...
```

The model will be trained with the exact phoneme ids you specify. You should set `--data.num_symbols <N>` to the number of phoneme ids you have unless you want the default of 256.

Setting `--data.phonemes_path <FILE>` will copy a phoneme/id map into the voice's config file (`--data.config_path`). This file is a JSON object mapping phonemes to ids:

```json
{
  "phoneme_1": 0,
  "phoneme_2": 1,
  ...
}
```

### Learning Rate Schedule

The learning rate decays once per epoch by `--model.lr_decay` (generator) and
`--model.lr_decay_d` (discriminators). Leave both unset and a decay is derived
from `--trainer.max_epochs` so that the learning rate ends the run at
`--model.lr_final_ratio` (default `0.05`) of where it started:

``` sh
python3 -m piper.train fit \
  ... \
  --trainer.max_epochs 100   # lr_decay becomes 0.05 ** (1/100) = 0.9705
```

Set `--trainer.max_epochs` if you want this. Runs are open-ended by default
(`max_epochs=-1`), and with no run length to anneal over the schedule falls back
to upstream VITS's `0.999875` — which was chosen for a ~20,000-epoch schedule and
decays the learning rate by only about 1% per 100 epochs. A warning is logged
when that happens.

Pass `--model.lr_decay`/`--model.lr_decay_d` to choose a decay yourself, or
`--model.lr_final_ratio 1.0` to hold the learning rate constant.

### How Long To Train

Choose the run length before you start and pass it as `--trainer.max_epochs`.
The [learning rate anneal](#learning-rate-schedule) is derived from it, so a run
stopped early never finishes its anneal, and a finished run that is extended
keeps decaying from its already-low learning rate instead of starting over.

These starting points have produced good voices, at batch sizes from 16 to 64
with the default anneal to 5%:

| Starting from | Audio | `--trainer.max_epochs` | Vocoder passes |
|---|---|---|---|
| A Piper checkpoint (fine-tune) | under ~5 h | 2,000 | several hundred |
| A Piper checkpoint (fine-tune) | ~10-15 h | 650-850 | ~75 |
| Scratch | 15-30 h | from the formula below | 150-220 |

* **Small fine-tunes.** 2,000 epochs is the recipe behind recent voices made
  from 0.9-4 h of audio. A 0.9 h voice trained for 3,300 epochs sounded about
  the same as its 2,000-epoch run, so going longer is not clearly better.
* **Larger fine-tunes.** Runs sized for ~75 vocoder passes (e.g. 667 epochs on
  11.2 h) have worked. Size bigger corpora the same way, using the formula
  below. The trainer warns about these runs, because its ~150 threshold comes
  from training from scratch, and a fine-tune starts with a trained decoder.
  Far fewer does hurt: a 150-epoch fine-tune on 27 h (~8 passes) ended with a
  worse `val_mel` than its base had on the same clips.
* **From scratch.** Aim for at least ~150 passes, the point below which the
  trainer warns (reference points are [below](#why-epochs-not-steps)).

To turn a target number of passes into epochs at 22.05 kHz with the default
`--model.segment_size`:

```
epochs ≈ passes x mean utterance seconds / 0.37
```

so 75 passes over clips that average 3.2 s is about 650 epochs.

All of these counts are for a run that starts at epoch 0, which is what
`--model.warmstart_ckpt <checkpoint>` does: it copies the checkpoint's weights
and starts a fresh optimizer and schedule. `--ckpt_path` instead resumes the
checkpoint's epoch counter, optimizer and model hyperparameters, which override
any `--model.*` flags. `--trainer.max_epochs` then has to include the epochs
already in the checkpoint. The Lessac `medium` checkpoint, for example, is at
epoch 2164, and it brings its `lr_decay` of 0.999875 along with it, so a
fine-tune from it runs at a nearly constant learning rate.

For wall-clock time, an epoch on an H100 at batch 48 takes roughly 9 s plus 4 s
per hour of audio, so 2,000 epochs of a 2 h voice takes about 10 h. On a 3090 at
batch 24, budget roughly 25 s per hour of audio per epoch, and on an A6000 at
batch 32, roughly 20 s.

#### Why epochs, not steps

Run length is usually chosen as a step count, but that is the wrong unit for
two of the modules. The decoder only ever sees one random `--model.segment_size`
window per utterance per epoch (8192 samples, about 0.37 s at 22.05 kHz), so its
real exposure is **passes over the training waveform**:

```
vocoder passes = epochs x segment_size / mean utterance samples
```

That scales with *epochs*, not steps. Growing the corpus at a fixed step budget
divides it: the same step count that gives a 17 h corpus ~160 passes gives a
290 h corpus ~18. The duration predictor is in the same position — it sees each
utterance once per epoch. A model can complete its entire learning-rate anneal
with both still badly underfit, and the segment-scoped training losses will not
say so.

For reference, the published VITS/LJSpeech recipe works out to ~220 passes and
the Piper Lessac checkpoint to ~163. The coverage is logged at the start of
training, with a warning below ~150:

```
Vocoder coverage: ~190 passes over the training waveform
(3774 epochs x 8192 samples / 158760 mean samples per utterance).
```

If that number is low, the fixes are a smaller corpus, a larger
`--model.segment_size`, a larger batch, or more epochs — not more steps at the
same epoch count. `segment_size` is not written into the preprocessed cache, so
it can be changed on a resume without rebuilding.

**Step counts are doubled.** `VitsModel` uses manual optimization and steps both
the generator and the discriminator in each `training_step`, so Lightning's
`global_step` — the number in progress bars and in checkpoint filenames like
`epoch=2164-step=1355540.ckpt` — counts two per batch. The real iteration count
is half of it, and is logged separately as `iters`.

### Validation Metrics

| Metric | Monitor | What it measures |
|---|---|---|
| `val_mel` | `min` | Mel L1 over the random `segment_size` window the generator trains on. Local spectral match on ~0.37 s. Saturates early. |
| `val_vocoder_mel` | `min` | Mel L1 between the real waveform and the decoder's own reconstruction of it, teacher forced over the **whole** utterance. No text encoder, alignment or duration predictor involved, so it moves with vocoder fit alone. |
| `val_mos` | `max` | UTMOS on the synthesized test clips. Perceptual proxy; noisy, and insensitive to some vocoder artifacts. See [MOS](#mos-val_mos). |

`val_mel` is a good general target but cannot distinguish a converged decoder
from one that has seen each waveform a handful of times — it is scored on the
same window the decoder trains on. Watch `val_vocoder_mel` alongside it when you
suspect the vocoder rather than the alignment.

### MOS (`val_mos`)

`val_mos` is the mean score that [UTMOS22][utmos] (its "strong" model; roughly
1-5, higher is better) gives the held-out test utterances, which are synthesized
at the end of every validation epoch. There are `--data.num_test_examples` of
them (default 5). They are the clips in TensorBoard's audio tab, and they are
synthesized at the default inference settings: `noise_scale` 0.667,
`length_scale` 1.0, `noise_w` 0.8.

The predictor is downloaded through `torch.hub` the first time it is needed,
cached under `~/.cache/torch/hub`, and run on the CPU. If it cannot be loaded,
for example on a training machine without network access, a warning is logged
and training carries on without `val_mos` or its checkpoints. Copy
`~/.cache/torch/hub` over from a machine that has it, or turn the metric off
with `--model.mos_metric none`.

What to expect from it:

* **It is noisy.** On a model that has stopped improving, it still has a
  standard deviation of 0.1-0.15 across epochs. Read the trend rather than
  single epochs. A larger `--data.num_test_examples` (say 20) averages out more
  of the noise at the cost of longer validation. Set it when the run starts,
  because changing it re-deals the split (see [below](#comparing-runs)).
* **The best `val_mos` is often a lucky epoch.** Keeping the top 5 of hundreds
  of noisy readings selects for noise. In four annealed runs, the best
  `val_mos` came anywhere from 40% of the way through to near the end, and the
  final epoch scored within 0.04 of it every time.
* **The number depends on the language and the speaker.** UTMOS was trained on
  listening tests of mostly English speech. Single-speaker English voices
  score around 4.2-4.3. German, French, Spanish, Chinese and Korean voices
  trained with this code have peaked at 3.3-3.8. Compare runs of the same
  voice, or voices in one language reading the same text, and never compare
  across languages.
* **It only measures how natural the audio sounds.** It barely notices a
  wrong phoneme, a wrong tone, a stray accent, or prosody that doesn't suit the
  voice. Of two fine-tunes of the same speaker that scored 4.28 and 4.27, the
  lower-scoring one was clearly preferred in listening. Listen before you
  publish.
* **It is scored at `noise_w` 0.8**, so it includes the duration jitter of the
  default settings. If you ship calmer settings, score those yourself (see
  [Choosing a Checkpoint](#choosing-a-checkpoint)).

#### Comparing runs

`val_mos`, `val_mel` and `val_vocoder_mel` can only be compared between runs
that share a validation split. The split is drawn at random, seeded by
`--seed_everything` (0 by default). It is re-dealt when the CSV,
`--data.validation_split` or `--data.num_test_examples` changes. It also changes
with the model's architecture flags, because initializing the model draws
random numbers before the split is drawn. After a resume, a step change in
`val_mel` that is several times its usual epoch-to-epoch wobble means the split
changed, not the model. A re-dealt split also validates on clips the model has
already trained on.

### Length Bucketing

Batches are padded to their longest member, and by default nothing orders the
data, so on a corpus with a long duration tail almost every batch is padded to
near that tail. On a corpus with p50 7 s and a tail to 20 s this measures at
~61% of each batch being padding.

``` sh
python3 -m piper.train fit \
  ... \
  --data.length_bucketing true
```

Each epoch the indices are shuffled, cut into windows of
`--data.bucket_multiplier` batches (default 32), sorted by length inside the
window, and split into batches whose order is then shuffled again — so batches
stay stochastic but become length-homogeneous. On the corpus above this takes
padding to ~3%.

It is off by default because it changes batch composition, and so changes the
training distribution of a schedule already in progress. Turn it on for a new
run rather than partway through one.

### Vocoder Warmstart

When training a new model from scratch, you can significantly speed up training by using `--model.vocoder_warmstart_ckpt <CHECKPOINT>`. This will copy the model parameters for the vocoder, but not the phoneme embedding layer.

Unlike `--ckpt_path`, using `--model.vocoder_warmstart_ckpt` allows you to train a model with a different number of phonemes without having to start completely from scratch.

## Choosing a Checkpoint

Each run writes its checkpoints to `lightning_logs/version_N/checkpoints/` under
`--trainer.default_root_dir` (the current directory by default):

* `epoch=N-val_mel=X.ckpt`: the 5 lowest `val_mel`
* `epoch=N-val_mos=X.ckpt`: the 5 highest `val_mos`
* `last.ckpt`: the latest epoch, rewritten every epoch

Every resume starts a new `version_N`, so look through all of them.

With an annealed learning rate, start with `last.ckpt`. By the end of the
anneal it is usually within noise of the best `val_mos` and close to the best
`val_mel`. Listen to it against the best `val_mos` and best `val_mel`
checkpoints on sentences that are not in the training set, at the inference
settings you plan to ship. If they sound the same, keep the later one. An
open-ended run (the default) never settles like this, so rely on listening even
more.

To see what a checkpoint recorded:

``` python
import torch

ckpt = torch.load("last.ckpt", map_location="cpu", weights_only=False)
print("epoch", ckpt["epoch"])
for state in ckpt["callbacks"].values():
    if state.get("monitor"):
        print(state["monitor"], float(state["best_model_score"]), state["best_model_path"])
```

To score audio you synthesized yourself (another checkpoint, an exported voice,
other inference settings) with the same predictor:

``` python
import librosa
import torch

from piper.train.vits.mos import MosPredictor

predictor = MosPredictor()
audio, sample_rate = librosa.load("sample.wav", sr=None, mono=True)
print(predictor.score(torch.from_numpy(audio), sample_rate))
```

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
[libritts-r]: https://www.openslr.org/141/
[espeak-ng]: https://github.com/espeak-ng/espeak-ng
[lighting]: https://lightning.ai/docs/pytorch/stable/
[librosa]: https://librosa.org/doc/latest/index.html
[piper-checkpoints]: https://huggingface.co/datasets/rhasspy/piper-checkpoints
[audio-config]: https://github.com/rhasspy/piper/blob/9b1c6397698b1da11ad6cca2b318026b628328ec/src/python/piper_train/vits/config.py#L20
[utmos]: https://github.com/tarepan/SpeechMOS
