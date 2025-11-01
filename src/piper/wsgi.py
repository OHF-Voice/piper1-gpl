"""Creates a WSGI application from process environment variables."""

from os import getenv
from pathlib import Path
from typing import Callable, Optional, TypeVar

from flask import Flask

from .http_server import AppArgs, create_app

T = TypeVar("T")
U = TypeVar("U")


def map_if_not_none(mapper: Callable[[T], U], value: Optional[T]) -> Optional[U]:
    return None if value is None else mapper(value)


def require(value: Optional[T]) -> T:
    if value is None:
        raise ValueError("Must be set.")
    else:
        return value


def create_app_args_from_env(
    get_env: Callable[[str], Optional[str]] = getenv,
) -> AppArgs:
    return AppArgs(
        model=require(get_env("PIPER_MODEL")),
        speaker=map_if_not_none(int, get_env("PIPER_SPEAKER")),
        length_scale=map_if_not_none(float, get_env("PIPER_LENGTH_SCALE")),
        noise_scale=map_if_not_none(float, get_env("PIPER_NOISE_SCALE")),
        noise_w_scale=map_if_not_none(float, get_env("PIPER_NOISE_W_SCALE")),
        cuda=(get_env("PIPER_CUDA") == "True"),
        sentence_silence=map_if_not_none(float, get_env("PIPER_SENTENCE_SILENCE"))
        or 0.0,
        data_dir=[d for d in (get_env("PIPER_DATA_DIR") or "").split(":") if d]
        or [str(Path.cwd())],
        download_dir=get_env("PIPER_DOWNLOAD_DIR"),
        debug=(get_env("PIPER_DEBUG") == "True"),
    )


def create_app_from_env() -> Flask:
    return create_app(create_app_args_from_env())
