"""Hebrew grapheme-to-phoneme with renikud.

renikud predicts a consonant, a vowel and the word stress for every letter of
unvocalized Hebrew text, so it goes straight from text to stressed IPA without a
niqqud step.

Inference-only port of ``renikud_onnx`` (https://github.com/renikud/renikud,
CC BY 4.0). The vocabularies and letter constraints are read from the ONNX
model's metadata, so the package is self-contained (no Hugging Face download at
runtime). See ``LICENSE`` and ``SOURCE`` in this directory.
"""

import json
import re
import unicodedata
from pathlib import Path
from typing import Dict, List, Set, Tuple, Union

import numpy as np
from onnxruntime import InferenceSession

HEBREW_DIR = Path(__file__).parent
DEFAULT_MODEL_PATH = HEBREW_DIR / "renikud.onnx"

ALEF_ORD = ord("א")
TAF_ORD = ord("ת")
STRESS_MARK = "ˈ"
ORTHOGRAPHIC_MARKERS = ("'", '"')


def _is_hebrew(char: str) -> bool:
    return ALEF_ORD <= ord(char) <= TAF_ORD


def normalize_graphemes(text: str) -> str:
    """Unify geresh / gershayim variants to ASCII ' and "."""
    text = re.sub(r"[׳'`´]", "'", text)
    text = re.sub(r'[״""]', '"', text)
    return text


class RenikudG2P:
    """Unvocalized Hebrew text -> IPA with stress marks."""

    def __init__(self, model_path: Union[str, Path] = DEFAULT_MODEL_PATH) -> None:
        self.session = InferenceSession(
            str(model_path), providers=["CPUExecutionProvider"]
        )
        meta = self.session.get_modelmeta().custom_metadata_map
        self._vocab: Dict[str, int] = json.loads(meta["vocab"])
        self._consonant_vocab: Dict[int, str] = {
            int(k): v for k, v in json.loads(meta["consonant_vocab"]).items()
        }
        self._vowel_vocab: Dict[int, str] = {
            int(k): v for k, v in json.loads(meta["vowel_vocab"]).items()
        }
        self._cls_id = int(meta["cls_token_id"])
        self._sep_id = int(meta["sep_token_id"])
        self._letter_constraints: Dict[str, List[int]] = json.loads(
            meta["letter_consonant_constraints"]
        )
        self._geresh_map: Dict[str, str] = json.loads(meta.get("geresh_map", "{}"))

    def _tokenize(
        self, normalized: str
    ) -> Tuple[List[int], List[int], List[Tuple[int, int]]]:
        """One token per character, plus CLS/SEP; returns ids, mask, offsets."""
        unk_id = self._vocab.get("[UNK]", 0)
        ids = [self._cls_id]
        offsets = [(0, 0)]
        for i, c in enumerate(normalized):
            ids.append(self._vocab.get(c, unk_id))
            offsets.append((i, i + 1))
        ids.append(self._sep_id)
        offsets.append((0, 0))
        return ids, [1] * len(ids), offsets

    @staticmethod
    def _best_stress_per_word(
        offsets: List[Tuple[int, int]], text: str, stress_logits: np.ndarray
    ) -> Set[int]:
        """Exactly one stressed letter per whitespace-separated word."""
        word_spans = [(m.start(), m.end()) for m in re.finditer(r"\S+", text)]
        words: Dict[int, List[int]] = {i: [] for i in range(len(word_spans))}
        for tok_idx, (start, end) in enumerate(offsets):
            if end - start != 1:
                continue
            for word_idx, (ws, we) in enumerate(word_spans):
                if ws <= start < we:
                    words[word_idx].append(tok_idx)
                    break
        return {
            max(toks, key=lambda t: stress_logits[t, 1])
            for toks in words.values()
            if toks
        }

    def __call__(self, text: str) -> str:
        normalized = unicodedata.normalize("NFD", normalize_graphemes(text))
        ids, mask, offsets = self._tokenize(normalized)
        consonant_logits, vowel_logits, stress_logits = self.session.run(
            ["consonant_logits", "vowel_logits", "stress_logits"],
            {
                "input_ids": np.array([ids], dtype=np.int64),
                "attention_mask": np.array([mask], dtype=np.int64),
            },
        )
        consonant_preds = consonant_logits[0].argmax(axis=-1)
        vowel_preds = vowel_logits[0].argmax(axis=-1)
        stressed = self._best_stress_per_word(offsets, normalized, stress_logits[0])

        result: List[str] = []
        prev_end = 0
        for tok_idx, (start, end) in enumerate(offsets):
            if end - start != 1:  # CLS / SEP
                if end > start:
                    prev_end = end
                continue

            if start > prev_end:  # characters the tokenizer skipped
                result.append(normalized[prev_end:start])

            char = normalized[start:end]
            prev_end = end

            if not _is_hebrew(char):
                if char not in ORTHOGRAPHIC_MARKERS:
                    result.append(char)  # passthrough
                continue

            cid = int(consonant_preds[tok_idx])
            allowed = self._letter_constraints.get(char)
            if (allowed is not None) and (cid not in allowed):
                cid = allowed[int(np.argmax(consonant_logits[0][tok_idx, allowed]))]
            consonant = self._consonant_vocab.get(cid, "∅")

            # Geresh: a following apostrophe forces the geresh consonant variant
            if (
                (char in self._geresh_map)
                and (end < len(normalized))
                and (normalized[end] == "'")
            ):
                consonant = self._geresh_map[char]

            vowel = self._vowel_vocab.get(int(vowel_preds[tok_idx]), "∅")
            stress = tok_idx in stressed

            # Word-final ח with /a/ is a furtive patah: [ˈ]aχ, vowel first
            word_final = (end >= len(normalized)) or (not normalized[end].isalpha())
            chunk = ""
            if (char == "ח") and word_final and (vowel == "a"):
                chunk = (STRESS_MARK if stress else "") + "aχ"
            else:
                if consonant != "∅":
                    chunk += consonant
                if stress:
                    chunk += STRESS_MARK
                if vowel != "∅":
                    chunk += vowel
            result.append(chunk)

        if prev_end < len(normalized):
            result.append(normalized[prev_end:])

        return "".join(result)
