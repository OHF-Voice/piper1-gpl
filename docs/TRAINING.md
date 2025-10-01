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

Run `python3 -m piper.train fit --help` to view all options. Alternatively, they are provided here:

```txt
usage: __main__.py [options] fit [-h] [-c CONFIG] [--print_config[=flags]] [--seed_everything SEED_EVERYTHING] [--trainer CONFIG] [--trainer.accelerator.help CLASS_PATH_OR_NAME]

      [--trainer.accelerator ACCELERATOR] [--trainer.strategy.help CLASS_PATH_OR_NAME] [--trainer.strategy STRATEGY] [--trainer.devices DEVICES]
      [--trainer.num_nodes NUM_NODES] [--trainer.precision PRECISION] [--trainer.logger.help CLASS_PATH_OR_NAME] [--trainer.logger LOGGER]
      [--trainer.callbacks.help CLASS_PATH_OR_NAME] [--trainer.callbacks CALLBACKS] [--trainer.fast_dev_run FAST_DEV_RUN] [--trainer.max_epochs MAX_EPOCHS]
      [--trainer.min_epochs MIN_EPOCHS] [--trainer.max_steps MAX_STEPS] [--trainer.min_steps MIN_STEPS] [--trainer.max_time MAX_TIME]
      [--trainer.limit_train_batches LIMIT_TRAIN_BATCHES] [--trainer.limit_val_batches LIMIT_VAL_BATCHES] [--trainer.limit_test_batches LIMIT_TEST_BATCHES]
      [--trainer.limit_predict_batches LIMIT_PREDICT_BATCHES] [--trainer.overfit_batches OVERFIT_BATCHES] [--trainer.val_check_interval VAL_CHECK_INTERVAL]
      [--trainer.check_val_every_n_epoch CHECK_VAL_EVERY_N_EPOCH] [--trainer.num_sanity_val_steps NUM_SANITY_VAL_STEPS]
      [--trainer.log_every_n_steps LOG_EVERY_N_STEPS] [--trainer.enable_checkpointing {true,false,null}] [--trainer.enable_progress_bar {true,false,null}]
      [--trainer.enable_model_summary {true,false,null}] [--trainer.accumulate_grad_batches ACCUMULATE_GRAD_BATCHES]
      [--trainer.gradient_clip_val GRADIENT_CLIP_VAL] [--trainer.gradient_clip_algorithm GRADIENT_CLIP_ALGORITHM] [--trainer.deterministic DETERMINISTIC]
      [--trainer.benchmark {true,false,null}] [--trainer.inference_mode {true,false}] [--trainer.use_distributed_sampler {true,false}]
      [--trainer.profiler.help CLASS_PATH_OR_NAME] [--trainer.profiler PROFILER] [--trainer.detect_anomaly {true,false}] [--trainer.barebones {true,false}]
      [--trainer.plugins.help CLASS_PATH_OR_NAME] [--trainer.plugins PLUGINS] [--trainer.sync_batchnorm {true,false}]
      [--trainer.reload_dataloaders_every_n_epochs RELOAD_DATALOADERS_EVERY_N_EPOCHS] [--trainer.default_root_dir DEFAULT_ROOT_DIR]
      [--trainer.model_registry MODEL_REGISTRY] [--model CONFIG] [--model.sample_rate SAMPLE_RATE] [--model.num_speakers NUM_SPEAKERS] [--model.resblock RESBLOCK]
      [--model.resblock_kernel_sizes RESBLOCK_KERNEL_SIZES] [--model.resblock_dilation_sizes RESBLOCK_DILATION_SIZES] [--model.upsample_rates UPSAMPLE_RATES]
      [--model.upsample_initial_channel UPSAMPLE_INITIAL_CHANNEL] [--model.upsample_kernel_sizes UPSAMPLE_KERNEL_SIZES] [--model.filter_length FILTER_LENGTH]
      [--model.hop_length HOP_LENGTH] [--model.win_length WIN_LENGTH] [--model.mel_channels MEL_CHANNELS] [--model.mel_fmin MEL_FMIN] [--model.mel_fmax MEL_FMAX]
      [--model.inter_channels INTER_CHANNELS] [--model.hidden_channels HIDDEN_CHANNELS] [--model.filter_channels FILTER_CHANNELS] [--model.n_heads N_HEADS]
      [--model.n_layers N_LAYERS] [--model.kernel_size KERNEL_SIZE] [--model.p_dropout P_DROPOUT] [--model.n_layers_q N_LAYERS_Q]
      [--model.use_spectral_norm {true,false}] [--model.gin_channels GIN_CHANNELS] [--model.use_sdp {true,false}] [--model.segment_size SEGMENT_SIZE]
      [--model.learning_rate LEARNING_RATE] [--model.learning_rate_d LEARNING_RATE_D] [--model.betas [ITEM,...]] [--model.betas_d [ITEM,...]] [--model.eps EPS]
      [--model.lr_decay LR_DECAY] [--model.lr_decay_d LR_DECAY_D] [--model.init_lr_ratio INIT_LR_RATIO] [--model.warmup_epochs WARMUP_EPOCHS] [--model.c_mel C_MEL]
      [--model.c_kl C_KL] [--model.grad_clip GRAD_CLIP] [--model.dataset.help [CLASS_PATH_OR_NAME]] [--model.dataset DATASET] [--data CONFIG]
      --data.csv_path CSV_PATH --data.cache_dir CACHE_DIR --data.espeak_voice ESPEAK_VOICE --data.config_path CONFIG_PATH --data.voice_name VOICE_NAME
      [--data.audio_dir AUDIO_DIR] [--data.alignments_dir ALIGNMENTS_DIR] [--data.num_symbols NUM_SYMBOLS] [--data.batch_size BATCH_SIZE]
      [--data.validation_split VALIDATION_SPLIT] [--data.num_test_examples NUM_TEST_EXAMPLES] [--data.num_workers NUM_WORKERS] [--data.trim_silence {true,false}]
      [--data.keep_seconds_before_silence KEEP_SECONDS_BEFORE_SILENCE] [--data.keep_seconds_after_silence KEEP_SECONDS_AFTER_SILENCE]
      [--optimizer.help [CLASS_PATH_OR_NAME]] [--optimizer CONFIG | CLASS_PATH_OR_NAME | .INIT_ARG_NAME VALUE] [--lr_scheduler.help CLASS_PATH_OR_NAME]
      [--lr_scheduler CONFIG | CLASS_PATH_OR_NAME | .INIT_ARG_NAME VALUE] [--ckpt_path CKPT_PATH]
```

## Exporting

When your model is finished training, export it to onnx with:

``` sh
python3 -m piper.train.export_onnx \
  --checkpoint /path/to/checkpoint.ckpt \
  --output-file /path/to/model.onnx
```

To make this compatible with other Piper voices, rename `model.onnx` as `<language>-<name>-medium.onnx` (e.g., `en_US-lessac-medium.onnx`). Name the JSON config file that was written to `--data.config_path` the same with a `.json` extension. So you would have two files for the voice:

* `en_US-lessac-medium.onnx`
* `en_US-lessac-medium.onnx.json`

## Hardware

Most of the Piper voices were trained/fine-tuned on a Threadripper 1900X with 128GB of RAM and either an NVIDIA A6000 (48 GB VRAM) or a 3090 (24 GB VRAM).

Users have reported success with as little as 8GB of VRAM and alternative GPUs like the RX 7600.

<!-- Links -->
[espeak-ng]: https://github.com/espeak-ng/espeak-ng
[lighting]: https://lightning.ai/docs/pytorch/stable/
[librosa]: https://librosa.org/doc/latest/index.html
[piper-checkpoints]: https://huggingface.co/datasets/rhasspy/piper-checkpoints
[audio-config]: https://github.com/rhasspy/piper/blob/9b1c6397698b1da11ad6cca2b318026b628328ec/src/python/piper_train/vits/config.py#L20
