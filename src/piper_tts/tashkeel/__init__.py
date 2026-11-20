"""Python implementation of libtashkeel.

See: https://github.com/mush42/libtashkeel

Ported with the help of ChatGPT 2025-05-01.
"""

import json
from pathlib import Path
from typing import Optional, Union

import numpy as np
from onnxruntime import InferenceSession

TASHKEEL_DIR = Path(__file__).parent
CHAR_LIMIT = 12000
PAD = "_"
NUMERAL_SYMBOL = "#"
NUMERALS = set("0123456789٠١٢٣٤٥٦٧٨٩")
HARAKAT_CHARS = {"\u064c", "\u064d", "\u064e", "\u064f", "\u0650", "\u0651", "\u0652"}
ARABIC_DIACRITICS = set(map(chr, [1618, 1617, 1614, 1615, 1616, 1611, 1612, 1613]))
NORMALIZED_DIAC_MAP = {"َّ": "َّ", "ًّ": "ًّ", "ُّ": "ُّ", "ٌّ": "ٌّ", "ِّ": "ِّ", "ٍّ": "ٍّ"}
SUKOON = chr(0x652)


class TashkeelError(Exception):
    """Error for tashkeel."""


class TashkeelDiacritizer:
    """Add diacritics for Arabic text with libtashkeel."""

    def __init__(self, model_dir: Union[str, Path] = TASHKEEL_DIR) -> None:
        """Initialize diacritizer."""
        model_dir = Path(model_dir)
        self.session = InferenceSession(model_dir / "model.onnx")

        # Load JSON maps
        with open(
            model_dir / "input_id_map.json", "r", encoding="utf-8"
        ) as input_id_map_file:
            self.input_id_map: dict[str, int] = json.load(input_id_map_file)

        with open(
            model_dir / "target_id_map.json", "r", encoding="utf-8"
        ) as target_id_map_file:
            target_id_map: dict[str, int] = json.load(target_id_map_file)
            self.id_target_map: dict[int, str] = {
                i: c for c, i in target_id_map.items()
            }

        self.target_id_meta_chars: set[int] = {target_id_map[c] for c in [PAD]}

        with open(
            model_dir / "hint_id_map.json", "r", encoding="utf-8"
        ) as hint_id_map_file:
            self.hint_id_map: dict[str, int] = json.load(hint_id_map_file)

    def __call__(self, text: str, taskeen_threshold: Optional[float] = None) -> str:
        """Add diacritics using libtashkeel."""
        return self.diacritize(text)

    def diacritize(self, text: str, taskeen_threshold=None) -> str:
        """Add diacritics using libtashkeel."""
        text = text.strip()

        if len(text) > CHAR_LIMIT:
            raise TashkeelError(f"Text length cannot exceed {CHAR_LIMIT}")

        input_text, removed_chars = self._to_valid_chars(text)
        input_text, diacritics = self._extract_chars_and_diacritics(
            input_text, normalize_diacritics=True
        )

        input_ids = self._input_to_ids(input_text)
        diac_ids = self._hint_to_ids(diacritics)
        seq_length = len(input_ids)

        if seq_length == 0:
            return text

        target_ids, logits = self._infer(input_ids, diac_ids, seq_length)

        diacritics = self._target_to_diacritics(target_ids)
        if taskeen_threshold is None:
            return self._annotate_text_with_diacritics(text, diacritics, removed_chars)

        return self._annotate_text_with_diacritics_taskeen(
            text, diacritics, removed_chars, logits, taskeen_threshold
        )

    def _infer(
        self, input_ids: list[int], diac_ids: list[int], seq_length: int
    ) -> tuple[list[int], list[float]]:
        """Infer target ids and logits."""
        input_ids_arr = np.array(input_ids, dtype=np.int64).reshape(1, seq_length)
        diac_ids_arr = np.array(diac_ids, dtype=np.int64).reshape(1, seq_length)
        input_len_arr = np.array([seq_length], dtype=np.int64).reshape(1)

        inputs = {
            "char_inputs": input_ids_arr,
            "diac_inputs": diac_ids_arr,
            "input_lengths": input_len_arr,
        }

        outputs = self.session.run(None, inputs)

        # Output 0: target_ids (u8)
        # Output 1: logits (f32)
        target_ids = outputs[0].flatten().astype(np.uint8).tolist()
        logits = outputs[1].flatten().astype(np.float32).tolist()

        return target_ids, logits

    def _annotate_text_with_diacritics(
        self, input_text: str, diacritics: list[str], removed_chars: set[str]
    ) -> str:
        output: list[str] = []
        diac_iter = iter(diacritics)
        for c in input_text:
            if self._is_diacritic_char(c):
                continue

            if c in removed_chars:
                output.append(c)
            else:
                output.append(c)
                output.append(next(diac_iter, ""))

        return "".join(output)

    def _annotate_text_with_diacritics_taskeen(
        self,
        input_text: str,
        diacritics: list[str],
        removed_chars: set[str],
        logits: list[float],
        threshold: float,
    ) -> str:
        output: list[str] = []
        diac_iter = zip(diacritics, logits)
        for c in input_text:
            if self._is_diacritic_char(c):
                continue

            if c in removed_chars:
                output.append(c)
            else:
                output.append(c)
                diac, logit = next(diac_iter, ("", 0.0))
                if logit > threshold:
                    output.append(SUKOON)
                else:
                    output.append(diac)
        return "".join(output)

    def _is_diacritic_char(self, c) -> bool:
        return c in ARABIC_DIACRITICS

    def _extract_chars_and_diacritics(
        self, text: str, normalize_diacritics: bool = True
    ) -> tuple[str, list[str]]:
        text = text.lstrip("".join(ARABIC_DIACRITICS))

        clean_chars = []
        diacritics = []
        pending_diac = ""

        for c in list(text) + [" "]:  # emulate .chain(iter::once(' '))
            if self._is_diacritic_char(c):
                pending_diac += c
            else:
                clean_chars.append(c)
                diacritics.append(pending_diac)
                pending_diac = ""

        if clean_chars:
            clean_chars.pop()  # pop the trailing space equivalent
        if diacritics:
            diacritics.pop(0)  # remove initial empty

        if normalize_diacritics:
            for i, d in enumerate(diacritics):
                if d not in self.hint_id_map:
                    diacritics[i] = NORMALIZED_DIAC_MAP.get(d, "")

        return "".join(clean_chars), diacritics

    def _to_valid_chars(self, text: str) -> tuple[str, set[str]]:
        valid: list[str] = []
        invalid: set[str] = set()
        for c in text:
            if (c in self.input_id_map) or (c in ARABIC_DIACRITICS):
                valid.append(c)
            elif c in NUMERALS:
                valid.append(NUMERAL_SYMBOL)
            else:
                invalid.add(c)
        return "".join(valid), invalid

    def _input_to_ids(self, text: str) -> list[int]:
        return [self.input_id_map[c] for c in text]

    def _hint_to_ids(self, diacritics: list[str]) -> list[int]:
        return [self.hint_id_map[d] for d in diacritics]

    def _target_to_diacritics(self, target_ids: list[int]) -> list[str]:
        return [
            self.id_target_map[i]
            for i in target_ids
            if i not in self.target_id_meta_chars
        ]
