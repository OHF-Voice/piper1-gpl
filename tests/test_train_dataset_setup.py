"""VitsDataModule.setup() skips utterances whose cached tensors are missing."""

import logging
import types

import pytest

dataset_module = pytest.importorskip("piper.train.vits.dataset")
utils_module = pytest.importorskip("piper.train.vits.utils")

CACHE_SUFFIXES = ("phonemes.pt", "audio.pt", "spec.pt")


def _data_module(tmp_path, rows):
    audio_dir = tmp_path / "wavs"
    audio_dir.mkdir()
    lines = []
    for utt_id, text in rows:
        (audio_dir / f"{utt_id}.wav").write_bytes(b"")
        lines.append(f"{utt_id}|{text}\n")
    csv_path = tmp_path / "metadata.csv"
    csv_path.write_text("".join(lines), encoding="utf-8")
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    data = dataset_module.VitsDataModule(
        csv_path=csv_path,
        cache_dir=cache_dir,
        espeak_voice="en-us",
        config_path=tmp_path / "config.json",
        voice_name="test",
        audio_dir=audio_dir,
        batch_size=1,
        validation_split=0.0,
        num_test_examples=0,
    )
    data.piper_config = types.SimpleNamespace(speaker_id_map={})
    return data


def _write_cache(data, row_number, text, suffixes=CACHE_SUFFIXES):
    cache_id = utils_module.get_cache_id(row_number, text)
    for suffix in suffixes:
        (data.cache_dir / f"{cache_id}.{suffix}").write_bytes(b"")


def _dataset_size(data) -> int:
    return len(data.train_dataset) + len(data.val_dataset) + len(data.test_dataset)


@pytest.mark.parametrize(
    ("missing", "warning"),
    [
        ("phonemes.pt", "Missing phoneme ids"),
        ("audio.pt", "Missing normalized audio"),
        ("spec.pt", "Missing mel spec"),
    ],
)
def test_setup_skips_an_utterance_with_a_missing_cache_file(
    tmp_path, caplog, missing, warning
):
    data = _data_module(tmp_path, [("utt1", "hello"), ("utt2", "world")])
    _write_cache(data, 1, "hello", [s for s in CACHE_SUFFIXES if s != missing])
    _write_cache(data, 2, "world")

    with caplog.at_level(logging.WARNING):
        data.setup("fit")

    assert _dataset_size(data) == 1
    assert warning in caplog.text


def test_setup_raises_when_no_utterance_is_usable(tmp_path):
    data = _data_module(tmp_path, [("utt1", "hello")])

    with pytest.raises(ValueError, match="No usable utterances"):
        data.setup("fit")
