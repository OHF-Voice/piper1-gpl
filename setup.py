"""Needed so package data is included."""

import itertools
from pathlib import Path

from skbuild import setup

MODULE_DIR = Path(__file__).parent / "src" / "piper"
PIPER_DATA_FILES = ["py.typed", "espeakbridge.pyi"]
ESPEAK_NG_DATA_DIR = MODULE_DIR / "espeak-ng-data"
ESPEAK_NG_DATA_FILES = [
    f.relative_to(MODULE_DIR) for f in ESPEAK_NG_DATA_DIR.rglob("*") if f.is_file()
]
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

setup(
    name="piper-tts",
    version="1.3.1",
    description="Fast and local neural text-to-speech engine",
    url="http://github.com/OHF-voice/piper1-gpl",
    license="GPL-3.0-or-later",
    author="The Home Assistant Authors",
    author_email="hello@home-assistant.io",
    keywords=["home", "assistant", "tts", "text-to-speech"],
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Topic :: Multimedia :: Sound/Audio :: Speech",
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
        "alignment": [
            "onnx>=1,<2",
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
)
