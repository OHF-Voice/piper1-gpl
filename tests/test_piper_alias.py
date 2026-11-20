"""Tests for the deprecated ``piper`` alias of ``piper_tts`` (issue #182).

Each test runs in a fresh interpreter so the import-time warning and the
meta path finder are exercised from a clean ``sys.modules``.
"""

import subprocess
import sys
import textwrap
from pathlib import Path

_TESTS_DIR = Path(__file__).parent
_TEST_VOICE = _TESTS_DIR / "test_voice.onnx"


def _run(code: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, *args, "-c", textwrap.dedent(code)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_import_warns() -> None:
    result = _run("import piper", "-W", "error::DeprecationWarning")
    assert result.returncode != 0
    assert "renamed to 'piper_tts'" in result.stderr


def test_piper_tts_does_not_import_piper() -> None:
    result = _run(
        """
        import sys
        import piper_tts, piper_tts.voice, piper_tts.http_server
        assert "piper" not in sys.modules, sorted(sys.modules)
        """,
        "-W",
        "error::DeprecationWarning",
    )
    assert result.returncode == 0, result.stderr


def test_same_objects() -> None:
    result = _run(
        """
        import warnings
        warnings.simplefilter("ignore", DeprecationWarning)

        import piper
        import piper_tts
        from piper import PiperVoice, SynthesisConfig
        from piper.config import PhonemeType
        import piper.voice
        import piper.phonemize_espeak

        assert PiperVoice is piper_tts.PiperVoice
        assert SynthesisConfig is piper_tts.SynthesisConfig
        assert PhonemeType is piper_tts.config.PhonemeType
        assert piper.voice is piper_tts.voice
        assert piper.phonemize_espeak is piper_tts.phonemize_espeak
        assert sorted(piper.__all__) == sorted(piper_tts.__all__)

        # The real modules keep their own names and specs.
        assert piper_tts.voice.__name__ == "piper_tts.voice"
        assert piper_tts.voice.__spec__.name == "piper_tts.voice"
        assert piper.phonemize_espeak.__spec__.name == "piper_tts.phonemize_espeak"
        """
    )
    assert result.returncode == 0, result.stderr


def test_subpackage_alias() -> None:
    result = _run(
        """
        import warnings
        warnings.simplefilter("ignore", DeprecationWarning)

        import importlib.util
        import sys

        import piper.tashkeel
        import piper_tts.tashkeel

        assert piper.tashkeel is piper_tts.tashkeel
        assert sys.modules["piper.tashkeel"] is piper_tts.tashkeel
        assert importlib.util.find_spec("piper.does_not_exist") is None
        """
    )
    assert result.returncode == 0, result.stderr


def test_run_module_old_name(tmp_path: Path) -> None:
    output_path = tmp_path / "out.wav"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "piper",
            "-m",
            str(_TEST_VOICE),
            "-f",
            str(output_path),
            "--",
            "This is a test.",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert output_path.stat().st_size > 44


def test_run_submodule_old_name() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "piper.download_voices", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "usage" in result.stdout
