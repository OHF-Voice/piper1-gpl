"""Tests for counting the phonemes a voice was trained on."""

import json
import sys

import pytest

from piper.config import PiperConfig
from piper.phoneme_ids import DEFAULT_PHONEME_ID_MAP, phonemes_to_ids

torch = pytest.importorskip("torch")
phoneme_counts = pytest.importorskip("piper.train.phoneme_counts")
get_cache_id = pytest.importorskip("piper.train.vits.utils").get_cache_id

ID_MAP = {"_": [0], "^": [1], "$": [2], " ": [3], "a": [4], "b": [5], "c": [6]}


def test_counts_phonemes_and_skips_inserted_tokens() -> None:
    ids = phonemes_to_ids(["b", "a", " ", "a"], ID_MAP)
    counts = phoneme_counts.count_phoneme_ids([ids, ids], ID_MAP)

    assert counts == {" ": 2, "a": 4, "b": 2}
    # Id order, so diffs between configs stay stable.
    assert list(counts) == [" ", "a", "b"]


def test_counts_with_default_map() -> None:
    ids = phonemes_to_ids(list("həlˈoʊ"), DEFAULT_PHONEME_ID_MAP)
    counts = phoneme_counts.count_phoneme_ids([ids], DEFAULT_PHONEME_ID_MAP)

    assert counts == {"h": 1, "l": 1, "o": 1, "ə": 1, "ʊ": 1, "ˈ": 1}


def test_unknown_ids_are_skipped() -> None:
    assert phoneme_counts.count_phoneme_ids([[1, 4, 0, 99, 0, 2]], ID_MAP) == {"a": 1}


def test_phonemes_sharing_an_id_each_get_its_count() -> None:
    # Like the Chinese map, which folds "。" into ".".
    alias_map = {**ID_MAP, "。": [4]}
    counts = phoneme_counts.count_phoneme_ids([[1, 4, 0, 4, 0, 5, 0, 2]], alias_map)

    assert counts == {"a": 2, "。": 2, "b": 1}


def test_phoneme_with_several_ids_raises() -> None:
    with pytest.raises(ValueError):
        phoneme_counts.count_phoneme_ids([[1]], {"_": [0], "a": [1, 2]})


def _write_cache(tmp_path, rows, speaker_id_map=None):
    """Write a CSV and cached phoneme ids the way prepare_data names them."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    csv_path = tmp_path / "metadata.csv"
    csv_path.write_text("".join("|".join(row) + "\n" for row in rows), encoding="utf-8")

    for row_number, row in enumerate(rows, start=1):
        speaker_id = speaker_id_map[row[1]] if speaker_id_map else None
        cache_id = get_cache_id(row_number, row[-1], speaker_id=speaker_id)
        torch.save(
            torch.LongTensor(phonemes_to_ids(list(row[-1]), ID_MAP)),
            cache_dir / f"{cache_id}.phonemes.pt",
        )

    return csv_path, cache_dir


def test_finds_cached_files_by_csv_row(tmp_path) -> None:
    speakers = {"x": 0, "y": 1}
    csv_path, cache_dir = _write_cache(
        tmp_path, [("u1", "x", "ab"), ("u2", "y", "cc")], speakers
    )
    # Left over from an older CSV; must not be counted.
    torch.save(torch.LongTensor([4, 4, 4]), cache_dir / "9_0_stale.phonemes.pt")
    # A row whose audio was missing at prepare time has no cached file.
    with open(csv_path, "a", encoding="utf-8") as csv_file:
        print("u3|x|ba", file=csv_file)

    paths, num_missing = phoneme_counts.cached_phoneme_ids_paths(
        csv_path, cache_dir, speakers
    )

    assert num_missing == 1
    assert phoneme_counts.count_cached_phonemes(paths, ID_MAP) == {
        "a": 1,
        "b": 1,
        "c": 2,
    }


def test_sidecar_is_reused_until_the_id_map_changes(tmp_path) -> None:
    csv_path, cache_dir = _write_cache(tmp_path, [("u1", "ab")])
    paths, _ = phoneme_counts.cached_phoneme_ids_paths(csv_path, cache_dir, {})
    sidecar = cache_dir / phoneme_counts.SIDECAR_NAME

    first = phoneme_counts.count_cached_phonemes(paths, ID_MAP, sidecar)
    assert first == {"a": 1, "b": 1}

    # Same names and map: the sidecar answers without reading the files.
    for path in paths:
        path.unlink()
    assert phoneme_counts.count_cached_phonemes(paths, ID_MAP, sidecar) == first

    # A different map invalidates it and the files are read again.
    with pytest.raises(FileNotFoundError):
        phoneme_counts.count_cached_phonemes(paths, {**ID_MAP, "d": [7]}, sidecar)


def test_cli_edits_config_in_place_and_keeps_unknown_keys(
    tmp_path, monkeypatch
) -> None:
    csv_path, cache_dir = _write_cache(tmp_path, [("u1", "abc"), ("u2", "aa")])
    config_path = tmp_path / "voice.onnx.json"
    config_path.write_text(
        json.dumps(
            {
                "dataset": "test",
                "language": {"code": "en_US"},
                "phoneme_id_map": ID_MAP,
                "speaker_id_map": {},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "phoneme_counts",
            "--config",
            str(config_path),
            "--csv",
            str(csv_path),
            "--cache-dir",
            str(cache_dir),
        ],
    )
    phoneme_counts.main()

    config = json.loads(config_path.read_text(encoding="utf-8"))
    assert config["phoneme_counts"] == {"a": 3, "b": 1, "c": 1}
    assert config["dataset"] == "test"
    assert config["language"] == {"code": "en_US"}


def _config_dict() -> dict:
    return {
        "num_symbols": 256,
        "num_speakers": 1,
        "audio": {"sample_rate": 22050},
        "espeak": {"voice": "en-us"},
        "phoneme_id_map": ID_MAP,
    }


def test_piper_config_round_trips_phoneme_counts() -> None:
    config = PiperConfig.from_dict({**_config_dict(), "phoneme_counts": {"a": 3}})
    assert config.phoneme_counts == {"a": 3}
    assert config.to_dict()["phoneme_counts"] == {"a": 3}


def test_piper_config_without_counts_omits_the_key() -> None:
    config = PiperConfig.from_dict(_config_dict())
    assert config.phoneme_counts is None
    assert "phoneme_counts" not in config.to_dict()
