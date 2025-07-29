"""Needed so package data is included."""

import itertools
from pathlib import Path

import os
import sys
from skbuild import setup
from setuptools import Extension

MODULE_DIR = Path(__file__).parent / "src" / "piper"
PIPER_DATA_FILES = ["py.typed", "espeakbridge.pyi"]
ESPEAK_NG_DATA_FILES = []
TASHKEEL_DATA_DIR = MODULE_DIR / "tashkeel"
TASHKEEL_DATA_FILES = [
    (TASHKEEL_DATA_DIR / f_name).relative_to(MODULE_DIR)
    for f_name in (
        "model.onnx",
        "input_id_map.json",
        "target_id_map.json",
        "hint_id_map.json",
    )
]

# Define espeakbridge extension
espeakbridge_extension = Extension(
    "piper.espeakbridge",
    sources=[os.path.relpath(os.path.join(os.path.dirname(__file__), "src", "piper", "espeakbridge.c"))],
    include_dirs=[str(Path(sys.prefix) / "include" / "espeak-ng")],
    library_dirs=[str(Path(sys.prefix) / "lib")],
    libraries=["espeak-ng"],
)

setup(
    name="piper-tts",
    version="1.3.6",
    description="Fast and local neural text-to-speech engine",
    url="http://github.com/OHF-voice/piper1-gpl",
    license="GPL-3.0-or-later",
    author="The Home Assistant Authors",
    author_email="hello@home-assistant.io",
    keywords=["home", "assistant", "tts", "text-to-speech"],
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Topic :: Text Processing :: Linguistic",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
    ],
    python_requires=">=3.9",
    install_requires=[
        "onnxruntime>=1,<2",
    ],
    extras_require={
        "train": [
            "torch>=2,<3",
            "lightning>=2,<3",
            "tensorboard>=2,<3",
            "tensorboardX>=2,<3",
            "jsonargparse[signatures]>=4.27.7",
            "pathvalidate>=3,<4",
            "onnx>=1,<2",
            "pysilero-vad>=2.1,<3",
            "cython>=3,<4",
            "librosa<1",
        ],
        "dev": [
            "black==24.8.0",
            "flake8==7.1.1",
            "mypy==1.14.0",
            "pylint==3.2.7",
            "pytest==8.3.4",
            "build==1.2.2",
            "scikit-build<1",
            "cmake>=3.18,<4",
            "ninja>=1,<2",
        ],
        "http": [
            "flask>=3,<4",
        ],
    },
    packages=["piper", "piper.tashkeel", "piper.train"],
    package_dir={"": "src"},
    include_package_data=True,
    package_data={
        "piper": [
            str(p)
            for p in itertools.chain(
                PIPER_DATA_FILES, ESPEAK_NG_DATA_FILES, TASHKEEL_DATA_FILES
            )
        ],
    },
    cmake_install_dir="src/piper",
    entry_points={
        "console_scripts": [
            "piper = piper.__main__:main",
        ]
    },
    ext_modules=[espeakbridge_extension], # Added espeakbridge extension
)
