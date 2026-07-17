#!/usr/bin/env python3
import argparse
import json
import logging
import sys
import time
import unicodedata
import wave
from pathlib import Path

import numpy as np
import torch

from ..config import PhonemeType, PiperConfig
from ..phoneme_ids import phonemes_to_ids
from ..phonemize_espeak import EspeakPhonemizer
from .vits.lightning import VitsModel
from .vits.utils import audio_float_to_int16

_LOGGER = logging.getLogger("piper_train.infer")


def main() -> None:
    """Main entry point"""
    logging.basicConfig(level=logging.DEBUG)
    parser = argparse.ArgumentParser(prog="piper_train.infer")
    parser.add_argument(
        "--checkpoint", required=True, help="Path to model checkpoint (.ckpt)"
    )
    parser.add_argument(
        "--config", required=True, help="Path to JSON voice config file"
    )
    parser.add_argument("--output-dir", required=True, help="Path to write WAV files")
    #
    parser.add_argument("--noise-scale", type=float, default=0.667)
    parser.add_argument("--length-scale", type=float, default=1.0)
    parser.add_argument("--noise-w", type=float, default=0.8)
    #
    args = parser.parse_args()

    args.output_dir = Path(args.output_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    with open(args.config, "r", encoding="utf-8") as config_file:
        config = PiperConfig.from_dict(json.load(config_file))

    sample_rate = config.sample_rate

    # Phonemizer is created lazily depending on phoneme type
    espeak_phonemizer = None
    chinese_phonemizer = None

    model = VitsModel.load_from_checkpoint(args.checkpoint, map_location="cpu")

    # Inference only
    model.eval()

    with torch.no_grad():
        model.model_g.dec.remove_weight_norm()

    for i, line in enumerate(sys.stdin):
        line = line.strip()
        if not line:
            continue

        utt = json.loads(line)
        utt_id = str(i)
        text = utt["text"]
        speaker_id = utt.get("speaker_id")

        if (speaker_id is None) and (config.num_speakers > 1):
            speaker_id = 0

        # Text -> phonemes (grouped by sentence)
        if config.phoneme_type == PhonemeType.TEXT:
            # Phonemes = codepoints
            sentence_phonemes = [list(unicodedata.normalize("NFD", text))]
        elif config.phoneme_type == PhonemeType.PINYIN:
            from ..phonemize_chinese import ChinesePhonemizer

            if chinese_phonemizer is None:
                chinese_phonemizer = ChinesePhonemizer(Path.cwd() / "g2pW")

            sentence_phonemes = chinese_phonemizer.phonemize(text)
        else:
            if espeak_phonemizer is None:
                espeak_phonemizer = EspeakPhonemizer()

            sentence_phonemes = espeak_phonemizer.phonemize(
                config.espeak_voice, text, vowel_clusters=config.vowel_clusters
            )

        # Phonemes -> ids
        if config.phoneme_type == PhonemeType.PINYIN:
            from ..phonemize_chinese import phonemes_to_ids as chinese_phonemes_to_ids

            phoneme_ids_per_sentence = [
                chinese_phonemes_to_ids(phonemes, config.phoneme_id_map)
                for phonemes in sentence_phonemes
                if phonemes
            ]
        else:
            phoneme_ids_per_sentence = [
                phonemes_to_ids(phonemes, config.phoneme_id_map)
                for phonemes in sentence_phonemes
                if phonemes
            ]

        if not phoneme_ids_per_sentence:
            _LOGGER.warning("No phonemes for utterance %s: %s", utt_id, text)
            continue

        scales = [args.noise_scale, args.length_scale, args.noise_w]
        sid = torch.LongTensor([speaker_id]) if speaker_id is not None else None

        # Synthesize each sentence and concatenate into a single audio clip
        audios = []
        start_time = time.perf_counter()
        for phoneme_ids in phoneme_ids_per_sentence:
            text_tensor = torch.LongTensor(phoneme_ids).unsqueeze(0)
            text_lengths = torch.LongTensor([len(phoneme_ids)])

            sentence_audio = (
                model(text_tensor, text_lengths, scales, sid=sid).detach().numpy()
            )
            audios.append(audio_float_to_int16(sentence_audio))
        end_time = time.perf_counter()

        audio = np.concatenate(audios, axis=-1)

        audio_duration_sec = audio.shape[-1] / sample_rate
        infer_sec = end_time - start_time
        real_time_factor = (
            infer_sec / audio_duration_sec if audio_duration_sec > 0 else 0.0
        )

        _LOGGER.debug(
            "Real-time factor for %s: %0.2f (infer=%0.2f sec, audio=%0.2f sec)",
            i + 1,
            real_time_factor,
            infer_sec,
            audio_duration_sec,
        )

        output_path = args.output_dir / f"{utt_id}.wav"
        wav_file: wave.Wave_write = wave.open(str(output_path), "wb")
        with wav_file:
            wav_file.setframerate(sample_rate)
            wav_file.setsampwidth(2)
            wav_file.setnchannels(1)
            wav_file.writeframes(audio.tobytes())


if __name__ == "__main__":
    main()
