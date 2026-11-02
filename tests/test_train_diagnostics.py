"""Tests for the training diagnostics that make underfitting visible.

The regression these guard against: a Hi-Fi TTS base model trained over 290 h
completed its full learning-rate anneal and still had an audibly underfit
vocoder and duration predictor. Nothing in the logs said so.

The run had spent the same total compute as the published VITS recipe -- 50.1 M
samples against 51.2 M -- but only 324 epochs against 3,908, because the step
budget was held fixed while the corpus grew. The decoder sees one random
``segment_size`` window per utterance per epoch, so its exposure scales with
epochs rather than steps: 18 passes over the waveform where the recipe gives
220. ``val_mel`` could not show it, being an L1 over that same window.
"""

# Reaching for the private helpers is deliberate: they are what these tests
# are asserting about.
# pylint: disable=protected-access

import os
from typing import List, Optional

import pytest

lightning_module = pytest.importorskip("piper.train.vits.lightning")
dataset_module = pytest.importorskip("piper.train.vits.dataset")
torch = pytest.importorskip("torch")

VitsModel = lightning_module.VitsModel
CachedUtterance = dataset_module.CachedUtterance
LengthBucketSampler = dataset_module.LengthBucketSampler


class _StubTrainer:
    """Stands in for the bits of Trainer the diagnostics read."""

    def __init__(
        self, max_epochs: Optional[int] = 100, num_optimizers: int = 2
    ) -> None:
        self.max_epochs = max_epochs
        self.optimizers = [object()] * num_optimizers
        self.datamodule = None
        self.global_step = 0


def _tiny_model(**kwargs) -> "VitsModel":
    model = VitsModel(
        num_symbols=32,
        num_speakers=1,
        inter_channels=16,
        hidden_channels=16,
        filter_channels=32,
        n_layers=2,
        upsample_initial_channel=16,
        mos_metric=None,
        **kwargs,
    )
    model._trainer = _StubTrainer()
    return model


def _utterances(tmp_path, seconds: List[float], sample_rate: int = 22050):
    """Cached-utterance records whose audio files have realistic byte sizes.

    Only the size matters: cached audio is a 1-D float32 tensor, so both the
    sampler and the budget report read lengths with os.stat rather than
    loading every tensor.
    """
    utts = []
    for index, duration in enumerate(seconds):
        path = tmp_path / f"{index}.pt"
        path.write_bytes(b"\0" * (768 + int(duration * sample_rate) * 4))
        utts.append(
            CachedUtterance(
                phoneme_ids_path=path, audio_norm_path=path, audio_spec_path=path
            )
        )
    return utts


# --------------------------------------------------------------- gin_channels


def test_gin_channels_without_speakers_is_rejected() -> None:
    """Conditioning layers that can never fire are a misconfiguration.

    emb_g is only built when n_speakers > 1, so g is always None and every
    cond layer this would allocate -- about a quarter of the generator -- is
    dead weight. Fail rather than train a model whose conditioning silently
    does nothing.
    """
    with pytest.raises(ValueError, match="num_speakers"):
        _tiny_model(gin_channels=512)


def test_single_speaker_defaults_to_no_conditioning() -> None:
    model = _tiny_model()
    assert model.hparams.gin_channels == 0


def test_multi_speaker_defaults_to_conditioning() -> None:
    model = VitsModel(
        num_symbols=32,
        num_speakers=4,
        inter_channels=16,
        hidden_channels=16,
        filter_channels=32,
        n_layers=2,
        upsample_initial_channel=16,
        mos_metric=None,
    )
    assert model.hparams.gin_channels == 512


# ------------------------------------------------------------ step accounting


def test_true_global_step_halves_the_doubled_counter() -> None:
    """global_step counts optimizer steps, and training_step takes two.

    So the number in every log line and checkpoint filename is twice the
    batches actually seen. Budgeting against the raw value is what produced a
    run a third the intended length.
    """
    model = _tiny_model()
    model._trainer = _StubTrainer(num_optimizers=2)
    model.trainer.global_step = 1_566_216

    assert model.true_global_step == 783_108


def test_true_global_step_handles_a_single_optimizer() -> None:
    model = _tiny_model()
    model._trainer = _StubTrainer(num_optimizers=1)
    model.trainer.global_step = 1000

    assert model.true_global_step == 1000


# ---------------------------------------------------------- vocoder coverage


def test_mean_audio_samples_reads_lengths_from_disk(tmp_path) -> None:
    model = _tiny_model()
    utts = _utterances(tmp_path, [4.0] * 8)

    model._trainer.datamodule = type(
        "_DM", (), {"train_dataset": type("_DS", (), {"utts": utts})()}
    )()

    assert model._mean_audio_samples() == pytest.approx(4.0 * 22050, rel=1e-3)


def test_budget_warns_when_the_vocoder_is_starved(tmp_path, caplog) -> None:
    """The ten-reader case: a full anneal over far too few epochs."""
    model = _tiny_model(segment_size=8192)
    model._trainer = _StubTrainer(max_epochs=324)
    # 6.68 s mean utterance, as the 290 h merged corpus had.
    model._trainer.datamodule = type(
        "_DM",
        (),
        {
            "train_dataset": type(
                "_DS", (), {"utts": _utterances(tmp_path, [6.68] * 8)}
            )()
        },
    )()

    with caplog.at_level("WARNING"):
        model._log_training_budget()

    assert "vocoder passes" in caplog.text


def test_budget_is_quiet_when_coverage_is_healthy(tmp_path, caplog) -> None:
    """Reader 92 at the chosen budget: ~190 passes, nothing to say."""
    model = _tiny_model(segment_size=8192)
    model._trainer = _StubTrainer(max_epochs=3774)
    model._trainer.datamodule = type(
        "_DM",
        (),
        {
            "train_dataset": type(
                "_DS", (), {"utts": _utterances(tmp_path, [7.20] * 8)}
            )()
        },
    )()

    with caplog.at_level("WARNING"):
        model._log_training_budget()

    assert "Only ~" not in caplog.text


def test_budget_never_raises_without_a_datamodule() -> None:
    """A diagnostic must not be able to take down a run that was starting."""
    model = _tiny_model()
    model._trainer = _StubTrainer(max_epochs=100)

    model._log_training_budget()  # must not raise


# ------------------------------------------------------------ length bucketing


def _waste(batches, seconds) -> float:
    """Fraction of each padded batch that is padding."""
    used = total = 0.0
    for batch in batches:
        longest = max(seconds[i] for i in batch)
        used += sum(seconds[i] for i in batch)
        total += longest * len(batch)
    return 1.0 - (used / total)


def test_bucketing_covers_every_utterance_exactly_once(tmp_path) -> None:
    seconds = [1.0 + (i % 12) for i in range(256)]
    sampler = LengthBucketSampler(
        _utterances(tmp_path, seconds), batch_size=8, drop_last=False
    )

    flat = [i for batch in sampler for i in batch]
    assert sorted(flat) == list(range(256))


def test_bucketing_drops_only_the_ragged_tail(tmp_path) -> None:
    seconds = [1.0 + (i % 12) for i in range(100)]
    sampler = LengthBucketSampler(
        _utterances(tmp_path, seconds), batch_size=8, drop_last=True
    )

    batches = list(sampler)
    assert all(len(batch) == 8 for batch in batches)
    assert len(batches) == len(sampler) == 12


def test_bucketing_cuts_padding(tmp_path) -> None:
    """The point of the sampler, on a realistic duration tail.

    The merged Hi-Fi TTS corpus is p50 ~7 s with a tail to 20 s. Uniform
    shuffling pads nearly every batch to something near that tail.
    """
    import random

    random.seed(0)
    seconds = [
        random.choice([1.5] * 5 + [4] * 20 + [7] * 40 + [9] * 20 + [11] * 10 + [20] * 5)
        for _ in range(2048)
    ]
    utts = _utterances(tmp_path, seconds)

    generator = torch.Generator().manual_seed(0)
    bucketed = list(LengthBucketSampler(utts, batch_size=64, generator=generator))

    order = torch.randperm(len(utts), generator=generator).tolist()
    shuffled = [order[i : i + 64] for i in range(0, len(order) - 63, 64)]

    assert _waste(bucketed, seconds) < 0.10
    assert _waste(bucketed, seconds) < _waste(shuffled, seconds) / 4


def test_bucketing_still_shuffles(tmp_path) -> None:
    """Homogeneous batches, but not the same batches every epoch."""
    utts = _utterances(tmp_path, [1.0 + (i % 12) for i in range(512)])
    sampler = LengthBucketSampler(
        utts, batch_size=16, generator=torch.Generator().manual_seed(0)
    )

    assert list(sampler) != list(sampler)


def test_bucketing_tolerates_a_missing_cache_file(tmp_path) -> None:
    """A vanished tensor must not break sampler construction."""
    utts = _utterances(tmp_path, [4.0] * 16)
    os.unlink(utts[3].audio_norm_path)

    sampler = LengthBucketSampler(utts, batch_size=4, drop_last=False)
    assert sorted(i for batch in sampler for i in batch) == list(range(16))


# ------------------------------------------------------- validation audio tags


class _StubLogger:
    def __init__(self, experiment) -> None:
        self.experiment = experiment


class _StubExperiment:
    def __init__(self) -> None:
        self.audio: List[tuple] = []
        self.text: List[tuple] = []

    def add_audio(self, tag, snd, sample_rate=None, global_step=None):
        self.audio.append((tag, global_step))

    def add_text(self, tag, text, global_step=None):
        self.text.append((tag, text, global_step))


def test_audio_tags_are_url_safe_and_positional() -> None:
    """Transcripts must not become the tag the audio fetch is keyed by.

    TensorBoard requests each clip's bytes by tag, and transcripts carry the
    characters that need escaping there. Runs whose test set came from prose
    had half their clips render as zero length while the bytes on disk were
    intact; a run with plain prompts had none.
    """
    model = _tiny_model()
    experiment = _StubExperiment()
    model._logger = None  # not used; _log_audio_text reads self.logger

    transcripts = [
        '"No, really?"',
        "Don't you remember, Harvey?",
        "A & B",
        "plain sentence",
    ]
    for index, transcript in enumerate(transcripts):
        tag = f"val/{index:02d}"
        experiment.add_audio(tag, None, global_step=10)
        model._logged_audio_text[tag] = transcript

    tags = [tag for tag, _ in experiment.audio]
    assert tags == ["val/00", "val/01", "val/02", "val/03"]
    assert not any(ch in tag for tag in tags for ch in '"?&#%')


def test_audio_text_is_logged_once_per_transcript(monkeypatch) -> None:
    """The text dashboard gets one entry, not one per validation epoch."""
    model = _tiny_model()
    experiment = _StubExperiment()
    monkeypatch.setattr(
        type(model),
        "logger",
        property(lambda self: _StubLogger(experiment)),
        raising=False,
    )

    for _ in range(5):
        model._log_audio_text("val/00", "Don't you remember, Harvey?")

    assert len(experiment.text) == 1
    assert experiment.text[0][0] == "val/00"

    # A changed split writes the new transcript under the same tag.
    model._log_audio_text("val/00", "Something else entirely.")
    assert len(experiment.text) == 2


def test_audio_text_tolerates_a_logger_without_add_text(monkeypatch) -> None:
    model = _tiny_model()
    monkeypatch.setattr(
        type(model),
        "logger",
        property(lambda self: _StubLogger(object())),
        raising=False,
    )

    model._log_audio_text("val/00", "text")  # must not raise


def test_audio_text_skips_empty_transcripts(monkeypatch) -> None:
    model = _tiny_model()
    experiment = _StubExperiment()
    monkeypatch.setattr(
        type(model),
        "logger",
        property(lambda self: _StubLogger(experiment)),
        raising=False,
    )

    model._log_audio_text("val/00", None)
    model._log_audio_text("val/01", "")

    assert experiment.text == []
