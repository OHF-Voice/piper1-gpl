"""Utility methods."""

import logging
from pathlib import Path
from typing import Dict, Optional, Union

import numpy as np
import torch
from pathvalidate import sanitize_filename

_LOGGER = logging.getLogger(__name__)


def to_gpu(x: torch.Tensor) -> torch.Tensor:
    return x.contiguous().cuda(non_blocking=True)


def audio_float_to_int16(
    audio: np.ndarray, max_wav_value: float = 32767.0
) -> np.ndarray:
    """Normalize audio and convert to int16 range"""
    audio_norm = audio * (max_wav_value / max(0.01, np.max(np.abs(audio))))
    audio_norm = np.clip(audio_norm, -max_wav_value, max_wav_value)
    audio_norm = audio_norm.astype("int16")
    return audio_norm


def load_phonemes(phonemes_path: Union[str, Path]) -> Dict[str, int]:
    phonemes: Dict[str, int] = {}
    with open(phonemes_path, "r", encoding="utf-8") as phonemes_file:
        phoneme_idx = 0
        for line in phonemes_file:
            line = line.strip("\r\n")
            if not line:
                continue

            phonemes[line] = phoneme_idx
            phoneme_idx += 1

    return phonemes


def load_state_dict(model, saved_state_dict):
    state_dict = model.state_dict()
    new_state_dict = {}

    for k, v in state_dict.items():
        if k in saved_state_dict:
            # Use saved value
            new_state_dict[k] = saved_state_dict[k]
        else:
            # Use initialized value
            _LOGGER.debug("%s is not in the checkpoint", k)
            new_state_dict[k] = v

    model.load_state_dict(new_state_dict)


def get_cache_id(
    row_number: int, text: str, max_length: int = 50, speaker_id: Optional[int] = None
) -> str:
    speaker_id_str = ""
    if speaker_id is not None:
        speaker_id_str = f"_{speaker_id}"

    cache_id = str(row_number) + speaker_id_str + "_" + sanitize_filename(text)
    return cache_id[:max_length]
