"""Deprecated alias for :mod:`piper_tts`.

The package was renamed from ``piper`` to ``piper_tts`` because the unrelated
mouse configuration tool `libratbag/piper <https://github.com/libratbag/piper>`_
also installs a top-level ``piper`` package, so the two could not be installed
side by side by a system package manager (issue #182).

Importing ``piper`` or any ``piper.<submodule>`` still works and returns the
*same* module objects as ``piper_tts`` (``piper.voice is piper_tts.voice``), so
classes, ``isinstance`` checks and module state are shared. ``python3 -m
piper`` and ``python3 -m piper.<submodule>`` run the ``piper_tts`` code.

Nothing in ``piper_tts`` imports ``piper``, so this directory can be left out of
a system package. It will be removed in piper 2.0.
"""

import importlib
import importlib.abc
import importlib.machinery
import importlib.util
import sys
import warnings
from typing import Any

import piper_tts
from piper_tts import *  # noqa: F401,F403 pylint: disable=wildcard-import,unused-wildcard-import

__all__ = list(piper_tts.__all__)

_OLD = "piper"
_NEW = "piper_tts"

warnings.warn(
    "The 'piper' package was renamed to 'piper_tts'; "
    "'import piper' will stop working in piper 2.0",
    DeprecationWarning,
    stacklevel=2,
)


def __getattr__(name: str) -> Any:
    return getattr(piper_tts, name)


class _AliasLoader(importlib.abc.Loader):
    """Make ``piper.<x>`` resolve to the already-imported ``piper_tts.<x>``."""

    def __init__(self, real_name: str) -> None:
        self._real_name = real_name
        self._real_spec = None

    def create_module(self, spec):
        module = importlib.import_module(self._real_name)
        self._real_spec = module.__spec__
        return module

    def exec_module(self, module) -> None:
        # The import system overwrites __spec__ on the module returned by
        # create_module; put the real one back so piper_tts.<x> is untouched.
        module.__spec__ = self._real_spec

    # runpy (python3 -m piper.<x>) runs the code object instead of importing.
    def _real_loader(self):
        spec = importlib.util.find_spec(self._real_name)
        assert spec is not None and spec.loader is not None
        return spec.loader

    def get_code(self, fullname: str):
        return self._real_loader().get_code(self._real_name)

    def get_source(self, fullname: str):
        return self._real_loader().get_source(self._real_name)

    def is_package(self, fullname: str) -> bool:
        return self._real_loader().is_package(self._real_name)

    def get_filename(self, fullname: str) -> str:
        return self._real_loader().get_filename(self._real_name)


class _AliasFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if not fullname.startswith(_OLD + "."):
            return None

        real_name = _NEW + fullname[len(_OLD) :]
        real_spec = importlib.util.find_spec(real_name)
        if real_spec is None:
            return None

        return importlib.machinery.ModuleSpec(
            fullname,
            _AliasLoader(real_name),
            origin=real_spec.origin,
            is_package=real_spec.submodule_search_locations is not None,
        )


if not any(isinstance(finder, _AliasFinder) for finder in sys.meta_path):
    sys.meta_path.insert(0, _AliasFinder())
