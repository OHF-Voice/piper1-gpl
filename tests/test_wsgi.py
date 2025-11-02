"""Tests for `wsgi.py`."""

import time
from http.client import HTTPResponse
from pathlib import Path
from subprocess import PIPE, Popen
from typing import Optional
from urllib.request import Request, urlopen

import pytest

from piper.http_server import AppArgs
from piper.wsgi import create_app_args_from_env

_DIR = Path(__file__).parent
_TESTS_DIR = _DIR
_TEST_VOICE = _TESTS_DIR / "test_voice.onnx"
_GUNICORN = _TESTS_DIR.parent / ".venv/bin/gunicorn"
_SOCKET = "127.0.0.1:34075"
_START_TIMEOUT = 5
_READY_TIMEOUT = 10


def test_wsgi_tts() -> None:
    process: Optional[Popen[bytes]] = None
    try:
        process = Popen(
            [str(_GUNICORN), "--bind", _SOCKET, "piper.wsgi:create_app_from_env()"],
            stderr=PIPE,
            env={
                "PIPER_MODEL": str(_TEST_VOICE),
            },
        )

        stderr = process.stderr
        assert stderr is not None
        start_time = time.time()
        while True:
            line = stderr.readline()
            if line.find(b"Listening at:") >= 0:
                break
            time.sleep(0.02)
            assert time.time() - start_time < _START_TIMEOUT

        request = Request(
            url=f"http://{_SOCKET}",
            method="POST",
            headers={"Content-Type": "application/json"},
            data=b'{ "text": "Test." }',
        )
        response: HTTPResponse
        with urlopen(request, timeout=_READY_TIMEOUT) as response:
            assert 200 == response.status
            body = response.read()
            assert body.startswith(b"RIFFh\xac\x00\x00WAVEfmt ")
    finally:
        if process is not None:
            process.send_signal(15)


def to_env_var(arg: str) -> str:
    return f"PIPER_{arg.upper()}"


full_env = {
    "PIPER_MODEL": "some/model",
    "PIPER_SPEAKER": "42",
    "PIPER_LENGTH_SCALE": "1.421",
    "PIPER_NOISE_SCALE": "1.422",
    "PIPER_NOISE_W_SCALE": "1.423",
    "PIPER_CUDA": "True",
    "PIPER_SENTENCE_SILENCE": "0.42",
    "PIPER_DATA_DIR": "some/dir:other/dir",
    "PIPER_DOWNLOAD_DIR": "download/dir",
    "PIPER_DEBUG": "True",
}
full_app_args = AppArgs(
    model="some/model",
    speaker=42,
    length_scale=1.421,
    noise_scale=1.422,
    noise_w_scale=1.423,
    cuda=True,
    sentence_silence=0.42,
    data_dir=["some/dir", "other/dir"],
    download_dir="download/dir",
    debug=True,
)
required_args = ["model"]
optional_args = list(full_app_args.__dict__.keys() - required_args)
minimum_env = {name: full_env[name] for name in map(to_env_var, required_args)}
minimum_args_params = (
    {name: full_app_args.__dict__[name] for name in required_args}
    | {name: None for name in optional_args}
    | {
        "cuda": False,
        "sentence_silence": 0.0,
        "data_dir": [str(Path.cwd())],
        "debug": False,
    }
)
minimum_args = AppArgs(**minimum_args_params)


def test_create_app_args_from_env_succeeds_for_full_env():
    assert full_app_args == create_app_args_from_env(get_env=full_env.get)


def test_create_app_args_from_env_succeeds_for_minimal_env():
    assert minimum_args == create_app_args_from_env(get_env=minimum_env.get)


@pytest.mark.parametrize("optional_arg", optional_args)
def test_create_app_args_from_env_succeeds_for_each_optional_arg(optional_arg: str):
    optional_env_var = to_env_var(optional_arg)
    env = minimum_env | {
        optional_env_var: full_env[optional_env_var],
    }
    args_params = minimum_args_params | {
        optional_arg: full_app_args.__dict__[optional_arg]
    }
    expected_args = AppArgs(**args_params)
    assert expected_args == create_app_args_from_env(env.get)


@pytest.mark.parametrize("missing_arg", required_args)
def test_create_app_args_from_env_fails_for_missing_arg(missing_arg: str):
    env = minimum_env | {
        to_env_var(missing_arg): None,
    }
    with pytest.raises(ValueError):
        create_app_args_from_env(get_env=env.get)


broken_env = [
    ("PIPER_SPEAKER", "1.2"),
    ("PIPER_SPEAKER", ""),
    ("PIPER_LENGTH_SCALE", "foo"),
    ("PIPER_LENGTH_SCALE", ""),
    ("PIPER_NOISE_SCALE", "foo"),
    ("PIPER_NOISE_SCALE", ""),
    ("PIPER_NOISE_W_SCALE", "foo"),
    ("PIPER_NOISE_W_SCALE", ""),
    ("PIPER_SENTENCE_SILENCE", "foo"),
    ("PIPER_SENTENCE_SILENCE", ""),
]


@pytest.mark.parametrize("broken_name,broken_value", broken_env)
def test_create_app_args_from_env_fails_for_each_broken_arg(
    broken_name: str, broken_value: str
):
    env = full_env | {
        broken_name: broken_value,
    }
    with pytest.raises(ValueError):
        create_app_args_from_env(get_env=env.get)
