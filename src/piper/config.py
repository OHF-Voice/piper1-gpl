"""Piper configuration"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final, Mapping, Optional, Sequence

DEFAULT_NOISE_SCALE: Final = 0.667
DEFAULT_LENGTH_SCALE: Final = 1.0
DEFAULT_NOISE_W_SCALE: Final = 0.8

DEFAULT_HOP_LENGTH: Final = 256


class PhonemeType(str, Enum):
    ESPEAK = "espeak"
    TEXT = "text"
    PINYIN = "pinyin"  # zh-CN


@dataclass
class PiperConfig:
    """Piper configuration"""

    num_symbols: int
    """Number of phonemes."""

    num_speakers: int
    """Number of speakers."""

    sample_rate: int
    """Sample rate of output audio."""

    espeak_voice: str
    """Name of espeak-ng voice or alphabet."""

    phoneme_id_map: Mapping[str, Sequence[int]]
    """Phoneme -> [id,]."""

    phoneme_type: PhonemeType
    """espeak or text."""

    speaker_id_map: Mapping[str, int] = field(default_factory=dict)
    """Speaker -> id"""

    piper_version: Optional[str] = None

    # Inference settings
    length_scale: float = DEFAULT_LENGTH_SCALE
    noise_scale: float = DEFAULT_NOISE_SCALE
    noise_w_scale: float = DEFAULT_NOISE_W_SCALE

    hop_length: int = DEFAULT_HOP_LENGTH

    @staticmethod
    def from_dict(config: dict[str, Any]) -> "PiperConfig":
        """Load configuration from a dictionary."""
        inference = config.get("inference", {})

        return PiperConfig(
            num_symbols=config["num_symbols"],
            num_speakers=config["num_speakers"],
            sample_rate=config["audio"]["sample_rate"],
            noise_scale=inference.get("noise_scale", DEFAULT_NOISE_SCALE),
            length_scale=inference.get("length_scale", DEFAULT_LENGTH_SCALE),
            noise_w_scale=inference.get("noise_w", DEFAULT_NOISE_W_SCALE),
            #
            espeak_voice=config["espeak"]["voice"],
            phoneme_id_map=config["phoneme_id_map"],
            phoneme_type=PhonemeType(config.get("phoneme_type", PhonemeType.ESPEAK)),
            speaker_id_map=config.get("speaker_id_map", {}),
            #
            piper_version=config.get("piper_version"),
            #
            hop_length=config.get("hop_length", DEFAULT_HOP_LENGTH),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert configuration to a dictionary."""
        config_dict = {
            "audio": {
                "sample_rate": self.sample_rate,
            },
            "espeak": {
                "voice": self.espeak_voice,
            },
            "phoneme_type": self.phoneme_type.value,
            "num_symbols": self.num_symbols,
            "num_speakers": self.num_speakers,
            "inference": {
                "noise_scale": self.noise_scale,
                "length_scale": self.length_scale,
                "noise_w": self.noise_w_scale,
            },
            "phoneme_id_map": self.phoneme_id_map,
            "speaker_id_map": self.speaker_id_map,
            "hop_length": self.hop_length,
        }

        if self.piper_version:
            config_dict["piper_version"] = self.piper_version

        return config_dict


@dataclass
class SynthesisConfig:
    """Configuration for Piper synthesis."""

    speaker_id: Optional[int] = None
    """Index of speaker to use (multi-speaker voices only)."""

    length_scale: Optional[float] = None
    """Phoneme length scale (< 1 is faster, > 1 is slower)."""

    noise_scale: Optional[float] = None
    """Amount of generator noise to add."""

    noise_w_scale: Optional[float] = None
    """Amount of phoneme width noise to add."""

    normalize_audio: bool = True
    """Enable/disable scaling audio samples to fit full range."""

    volume: float = 1.0
    """Multiplier for audio samples (< 1 is quieter, > 1 is louder)."""
