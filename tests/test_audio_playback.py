"""Tests for ffplay audio playback."""

import subprocess
from unittest.mock import MagicMock, call, patch

import pytest

from piper.audio_playback import AudioPlayer


def _process_mock() -> MagicMock:
    process = MagicMock(spec=subprocess.Popen)
    process.stdin = MagicMock()
    return process


@pytest.mark.parametrize(
    ("chunks", "expected_timeout"),
    [
        ([], 5.0),
        ([2 * 10], 5.0),
        ([2 * 10 * 12], 13.0),
        ([2 * 10 * 6, 2 * 10 * 6], 13.0),
    ],
)
def test_wait_timeout_scales_with_audio_duration(
    chunks: list[int], expected_timeout: float
) -> None:
    """Wait long enough for ffplay to drain all streamed audio."""
    process = _process_mock()
    process.stdin.write.side_effect = chunks
    events = []
    process.stdin.close.side_effect = lambda: events.append("close")
    process.wait.side_effect = lambda **kwargs: events.append("wait")

    with patch("piper.audio_playback.subprocess.Popen", return_value=process):
        with AudioPlayer(sample_rate=10) as player:
            for chunk_size in chunks:
                player.play(bytes(chunk_size))

    assert events == ["close", "wait"]
    process.wait.assert_called_once_with(timeout=expected_timeout)


def test_failed_write_does_not_extend_wait_timeout() -> None:
    """Do not count bytes that ffplay did not accept."""
    process = _process_mock()
    process.stdin.write.side_effect = OSError("write failed")

    with patch("piper.audio_playback.subprocess.Popen", return_value=process):
        with pytest.raises(OSError, match="write failed"):
            with AudioPlayer(sample_rate=10) as player:
                player.play(bytes(2 * 10 * 12))

    process.wait.assert_called_once_with(timeout=5.0)


def test_timeout_kills_ffplay_and_remains_bounded() -> None:
    """Clean up ffplay when it does not exit within the calculated timeout."""
    process = _process_mock()
    process.wait.side_effect = [
        subprocess.TimeoutExpired("ffplay", 5.0),
        None,
    ]

    with patch("piper.audio_playback.subprocess.Popen", return_value=process):
        with pytest.raises(subprocess.TimeoutExpired):
            with AudioPlayer(sample_rate=10):
                pass

    process.kill.assert_called_once_with()
    assert process.wait.call_args_list == [
        call(timeout=5.0),
        call(timeout=1.0),
    ]


def test_reentering_player_resets_audio_duration() -> None:
    """Track duration per ffplay process instead of per player instance."""
    first_process = _process_mock()
    first_process.stdin.write.return_value = 2 * 10 * 12
    second_process = _process_mock()
    player = AudioPlayer(sample_rate=10)

    with patch(
        "piper.audio_playback.subprocess.Popen",
        side_effect=[first_process, second_process],
    ):
        with player:
            player.play(bytes(2 * 10 * 12))
        with player:
            pass

    first_process.wait.assert_called_once_with(timeout=13.0)
    second_process.wait.assert_called_once_with(timeout=5.0)
