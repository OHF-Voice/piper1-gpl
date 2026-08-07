"""Audio playback using ffplay."""

import shutil
import subprocess
from typing import Optional

_BYTES_PER_SAMPLE = 2
_MIN_PROCESS_WAIT_SECONDS = 5.0
_PROCESS_WAIT_MARGIN_SECONDS = 1.0
_PROCESS_KILL_WAIT_SECONDS = 1.0


class AudioPlayer:
    """Plays raw audio using ffplay."""

    def __init__(self, sample_rate: int) -> None:
        """Initializes audio player."""
        self.sample_rate = sample_rate
        self._proc: Optional[subprocess.Popen] = None
        self._audio_bytes_written = 0

    def __enter__(self):
        """Starts ffplay subprocess and returns player."""
        self._audio_bytes_written = 0
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

            audio_duration = self._audio_bytes_written / (
                self.sample_rate * _BYTES_PER_SAMPLE
            )
            wait_timeout = max(
                _MIN_PROCESS_WAIT_SECONDS,
                audio_duration + _PROCESS_WAIT_MARGIN_SECONDS,
            )
            try:
                self._proc.wait(timeout=wait_timeout)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait(timeout=_PROCESS_KILL_WAIT_SECONDS)
                raise

    def play(self, audio_bytes: bytes) -> None:
        """Plays raw audio using ffplay."""
        assert self._proc is not None
        assert self._proc.stdin is not None

        bytes_written = self._proc.stdin.write(audio_bytes)
        self._audio_bytes_written += bytes_written
        self._proc.stdin.flush()

    @staticmethod
    def is_available() -> bool:
        """Returns true if ffplay is available."""
        return bool(shutil.which("ffplay"))
