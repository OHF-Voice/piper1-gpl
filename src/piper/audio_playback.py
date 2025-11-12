"""Audio playback using ffplay."""

import shutil
import subprocess
from typing import Optional


class AudioPlayer:
    """Plays raw audio using ffplay."""

    def __init__(self, sample_rate: int) -> None:
        """Initializes audio player."""
        self.sample_rate = sample_rate
        self._proc: Optional[subprocess.Popen] = None

    def __enter__(self):
        """Starts ffplay subprocess and returns player."""
        self._proc = subprocess.Popen(
            [
                "ffplay",
                "-nodisp",
                "-autoexit",
                "-f",
                "s16le",
                "-sample_rate",
                str(self.sample_rate),
                "-ch_layout",
                "mono",
                "-",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Stops ffplay subprocess."""
        if self._proc:
            try:
                if self._proc.stdin:
                    self._proc.stdin.close()
            except Exception:
                pass
            self._proc.wait(timeout=5)

    def play(self, audio_bytes: bytes) -> None:
        """Plays raw audio using ffplay."""
        assert self._proc is not None
        assert self._proc.stdin is not None

        self._proc.stdin.write(audio_bytes)
        self._proc.stdin.flush()

    @staticmethod
    def is_available() -> bool:
        """Returns true if ffplay is available."""
        return bool(shutil.which("ffplay"))
