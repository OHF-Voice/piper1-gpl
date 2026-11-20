"""Count the phonemes a voice was trained on.

The counts come from the cached ``*.phonemes.pt`` id tensors, which are
exactly what the model saw: vowel clusters merged, phonemes missing from the
id map dropped, and phoneme-id datasets taken as-is. The ``*.phonemes.txt``
files can't be used, since each sentence is joined into one string and
multi-character phonemes can't be split back out of it.

As a script, this backfills ``phoneme_counts`` into the config of a voice that
was trained before the counts were written automatically::

    python3 -m piper_tts.train.phoneme_counts \\
        --config voice.onnx.json --csv metadata.csv --cache-dir cache/

The config is edited as raw JSON, so keys this version of Piper doesn't know
about are kept.
"""

import argparse
import csv
import hashlib
import json
import logging
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Optional

from piper_tts.const import BOS, EOS, PAD

from .vits.utils import get_cache_id

_LOGGER = logging.getLogger(__name__)

# Inserted around and between phonemes by phonemes_to_ids, never phonemized.
_NOT_COUNTED = (PAD, BOS, EOS)

SIDECAR_NAME = "phoneme_counts.json"


def _id_to_phonemes(
    phoneme_id_map: Mapping[str, Sequence[int]],
) -> dict[int, list[str]]:
    id_to_phonemes: dict[int, list[str]] = {}
    for phoneme, phoneme_ids in phoneme_id_map.items():
        if isinstance(phoneme_ids, int):
            phoneme_ids = [phoneme_ids]

        if len(phoneme_ids) != 1:
            raise ValueError(
                f"Phoneme {phoneme!r} maps to {len(phoneme_ids)} ids; "
                "counting needs exactly one id per phoneme"
            )

        # Several phonemes can share an id, e.g. the Chinese map folds "。"
        # and "." together.
        id_to_phonemes.setdefault(phoneme_ids[0], []).append(phoneme)

    return id_to_phonemes


def count_phoneme_ids(
    id_sequences: Iterable[Sequence[int]],
    phoneme_id_map: Mapping[str, Sequence[int]],
) -> dict[str, int]:
    """Count phonemes in sequences of phoneme ids.

    Returns phoneme -> count for phonemes that occur, in id order. Phonemes
    that share an id are aliases the model can't tell apart, so each one gets
    that id's count. PAD, BOS and EOS are not counted. Ids missing from the map
    are logged and skipped.
    """
    id_to_phonemes = _id_to_phonemes(phoneme_id_map)
    skip_ids = {
        phoneme_id
        for phoneme in _NOT_COUNTED
        for phoneme_id in phoneme_id_map.get(phoneme, [])
    }

    id_counts: Counter[int] = Counter()
    for phoneme_ids in id_sequences:
        id_counts.update(phoneme_ids)

    phoneme_counts: dict[str, int] = {}
    for phoneme_id in sorted(id_counts):
        if phoneme_id in skip_ids:
            continue

        phonemes = id_to_phonemes.get(phoneme_id)
        if phonemes is None:
            _LOGGER.warning(
                "Phoneme id %s is not in the id map (%s occurrence(s))",
                phoneme_id,
                id_counts[phoneme_id],
            )
            continue

        for phoneme in phonemes:
            phoneme_counts[phoneme] = id_counts[phoneme_id]

    return phoneme_counts


def _load_ids(phoneme_ids_path: Path) -> list[int]:
    import torch  # pylint: disable=import-outside-toplevel

    return torch.load(phoneme_ids_path).tolist()


def count_cached_phonemes(
    phoneme_ids_paths: Sequence[Path],
    phoneme_id_map: Mapping[str, Sequence[int]],
    sidecar_path: Optional[Path] = None,
) -> dict[str, int]:
    """Count phonemes in cached ``*.phonemes.pt`` files.

    With ``sidecar_path``, the result is saved there along with a key made from
    the file names and the id map, and reused while both are unchanged, so a
    large corpus is only read once. A cached file's name holds its CSV row
    number and text, and prepare_data never rewrites an existing one, so the
    names stand in for the contents.
    """
    key = _sidecar_key(phoneme_ids_paths, phoneme_id_map)
    if sidecar_path is not None:
        try:
            sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
            if sidecar.get("key") == key:
                return sidecar["phoneme_counts"]
        except (OSError, ValueError, KeyError, AttributeError):
            pass

    phoneme_counts = count_phoneme_ids(
        (_load_ids(path) for path in phoneme_ids_paths), phoneme_id_map
    )

    if sidecar_path is not None:
        sidecar_path.write_text(
            json.dumps(
                {"key": key, "phoneme_counts": phoneme_counts}, ensure_ascii=False
            ),
            encoding="utf-8",
        )

    return phoneme_counts


def _sidecar_key(
    phoneme_ids_paths: Sequence[Path], phoneme_id_map: Mapping[str, Sequence[int]]
) -> str:
    hasher = hashlib.sha256()
    hasher.update(
        json.dumps(phoneme_id_map, sort_keys=True, ensure_ascii=False).encode("utf-8")
    )
    for path in sorted(p.name for p in phoneme_ids_paths):
        hasher.update(b"\0")
        hasher.update(path.encode("utf-8"))

    return hasher.hexdigest()


def cached_phoneme_ids_paths(
    csv_path: Path,
    cache_dir: Path,
    speaker_id_map: Mapping[str, int],
    phoneme_ids_dataset: bool = False,
) -> tuple[list[Path], int]:
    """Find the cached phoneme id files for each row of a training CSV.

    Goes row by row rather than listing the cache dir, which can hold files
    left from an older version of the CSV. Multi-speaker is assumed when
    ``speaker_id_map`` is non-empty, as it is in a multi-speaker config.

    Returns the paths found and the number of rows with no cached file (rows
    whose audio was missing at prepare time have none).
    """
    paths: list[Path] = []
    num_missing = 0
    with open(csv_path, "r", encoding="utf-8") as csv_file:
        reader = csv.reader(csv_file, delimiter="|")
        for row_number, row in enumerate(reader, start=1):
            speaker_id: Optional[int] = None
            if speaker_id_map:
                speaker_id = speaker_id_map[row[1]]

            text = row[-2] if phoneme_ids_dataset else row[-1]
            cache_id = get_cache_id(row_number, text, speaker_id=speaker_id)
            path = cache_dir / f"{cache_id}.phonemes.pt"
            if path.exists():
                paths.append(path)
            else:
                num_missing += 1

    return paths, num_missing


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Write phoneme_counts into a voice config from its training cache"
    )
    parser.add_argument(
        "--config", required=True, help="Voice config (.onnx.json or config.json)"
    )
    parser.add_argument("--csv", required=True, help="Training metadata CSV")
    parser.add_argument(
        "--cache-dir", required=True, help="Training cache dir with *.phonemes.pt"
    )
    parser.add_argument(
        "--dataset-type",
        choices=("text", "phoneme_ids"),
        default="text",
        help="Dataset type the voice was trained with (default: text)",
    )
    parser.add_argument(
        "--output", help="Write the config here instead of editing --config in place"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the counts and don't write anything",
    )
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO)

    config_path = Path(args.config)
    with open(config_path, "r", encoding="utf-8") as config_file:
        config = json.load(config_file)

    paths, num_missing = cached_phoneme_ids_paths(
        Path(args.csv),
        Path(args.cache_dir),
        config.get("speaker_id_map") or {},
        phoneme_ids_dataset=(args.dataset_type == "phoneme_ids"),
    )
    if not paths:
        _LOGGER.fatal(
            "No cached phoneme ids found for %s in %s", args.csv, args.cache_dir
        )
        sys.exit(1)

    if num_missing:
        _LOGGER.warning(
            "%s of %s CSV row(s) have no cached phoneme ids and are not counted",
            num_missing,
            num_missing + len(paths),
        )

    phoneme_counts = count_cached_phonemes(paths, config["phoneme_id_map"])
    _LOGGER.info(
        "Counted %s distinct phoneme(s) of %s in the id map over %s utterance(s)",
        len(phoneme_counts),
        len(config["phoneme_id_map"]),
        len(paths),
    )

    if args.dry_run:
        for phoneme, count in sorted(
            phoneme_counts.items(), key=lambda item: item[1], reverse=True
        ):
            print(f"{phoneme!r}\t{count}")
        return

    config["phoneme_counts"] = phoneme_counts
    output_path = Path(args.output) if args.output else config_path
    with open(output_path, "w", encoding="utf-8") as output_file:
        json.dump(config, output_file, ensure_ascii=False, indent=2)
        print("", file=output_file)

    _LOGGER.info("Wrote %s", output_path)


if __name__ == "__main__":
    main()
