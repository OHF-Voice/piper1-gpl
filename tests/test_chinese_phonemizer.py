"""Tests for Chinese phonemization."""

from pathlib import Path

import pytest

from piper.phonemize_chinese import ChinesePhonemizer, phonemes_to_ids

PAD_ID = 0
BOS_ID = 1
EOS_ID = 2

TEST_DIR = Path(__file__).parent
REPO_DIR = TEST_DIR.parent
LOCAL_DIR = REPO_DIR / "local"
MODEL_DIR = LOCAL_DIR / "g2pW"


@pytest.fixture(name="phonemizer", scope="session")
def phonemizer_fixture() -> ChinesePhonemizer:
    return ChinesePhonemizer(model_dir=MODEL_DIR)


def test_phonemize(phonemizer: ChinesePhonemizer) -> None:
    phonemes = phonemizer.phonemize("卡尔普陪外孙玩滑梯。 假语村言别再拥抱我。")
    assert phonemes == [
        [
            "k",
            "a",
            "3",
            #
            "Ø",
            "er",
            "3",
            #
            "p",
            "u",
            "3",
            #
            "p",
            "ei",
            "2",
            #
            "w",
            "ai",
            "4",
            #
            "s",
            "un",
            "1",
            #
            "w",
            "an",
            "2",
            #
            "h",
            "ua",
            "2",
            #
            "t",
            "i",
            "1",
            #
            "。",
        ],
        [
            "j",
            "ia",
            "3",
            #
            "y",
            "u",
            "3",
            #
            "c",
            "un",
            "1",
            #
            "y",
            "an",
            "2",
            #
            "b",
            "ie",
            "2",
            #
            "z",
            "ai",
            "4",
            #
            "y",
            "ong",
            "3",
            #
            "b",
            "ao",
            "4",
            #
            "w",
            "o",
            "3",
            #
            "。",
        ],
    ]

    assert phonemes_to_ids(phonemes[0]) == [
        BOS_ID,
        # k a 3
        13,
        27,
        66,
        PAD_ID,
        # Ø er 3
        3,
        62,
        66,
        PAD_ID,
        # p u 3
        5,
        49,
        66,
        PAD_ID,
        # p ei 2
        5,
        31,
        65,
        PAD_ID,
        # w ai 4
        26,
        30,
        67,
        PAD_ID,
        # s un 1
        24,
        55,
        64,
        PAD_ID,
        # w an 2
        26,
        34,
        65,
        PAD_ID,
        # h ua 2
        14,
        50,
        65,
        PAD_ID,
        # t i 1
        9,
        39,
        64,
        PAD_ID,
        # 。
        69,
        #
        PAD_ID,
        EOS_ID,
    ]


@pytest.mark.parametrize(
    ("number_text", "word_text"),
    [
        # ------------------------
        # Basic integers
        # ------------------------
        ("我有123个苹果。", "我有一百二十三个苹果。"),
        ("他住在45楼，旁边是7号房间。", "他住在四十五楼，旁边是七号房间。"),
        # ------------------------
        # Negative / signed numbers
        # ------------------------
        ("今天室外温度是-5度。", "今天室外温度是负五度。"),
        (
            "股票下跌了-12点，指数变成3498点。",
            "股票下跌了负十二点，指数变成三千四百九十八点。",
        ),
        # ------------------------
        # Decimals
        # ------------------------
        ("这个房间面积是12.5平方米。", "这个房间面积是十二点五平方米。"),
        ("汽油价格涨到7.89元。", "汽油价格涨到七点八九元。"),
        # ------------------------
        # Mixed alphanumeric
        # ------------------------
        ("请打开5G网络。", "请打开五G网络。"),
        ("他买了一台4K电视。", "他买了一台四K电视。"),
        ("密码是123ABC。", "密码是一百二十三ABC。"),
        # ------------------------
        # Edge cases: punctuation / boundaries
        # ------------------------
        ("他跑了3000米，花了15分钟。", "他跑了三千米，花了十五分钟。"),
        ("总共是98.76%，差不多。", "总共是九十八点七六%，差不多。"),
        ("前面有0个人，后面有10个人。", "前面有零个人，后面有十个人。"),
    ],
)
def test_numbers_to_words(
    phonemizer: ChinesePhonemizer, number_text: str, word_text: str
) -> None:
    assert phonemizer.phonemize(number_text) == phonemizer.phonemize(word_text)
