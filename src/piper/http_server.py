"""Flask web server with HTTP API for Piper."""

import argparse
import io
import json
import logging
import wave
from dataclasses import dataclass
from os import getenv
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.request import urlopen

from flask import Flask, request

from . import PiperVoice, SynthesisConfig
from .download_voices import VOICES_JSON, download_voice

_LOGGER = logging.getLogger()

GetEnvType=Callable[[str], Optional[str]]


def create_argument_parser(get_env: GetEnvType = getenv) -> argparse.ArgumentParser:
    parser = create_environment_fallback_argument_parser(env_prefix="PIPER_", get_env=get_env)
    parser.add_argument("--host", default="0.0.0.0", help="HTTP server host")
    parser.add_argument("--port", type=int, default=5000, help="HTTP server port")
    #
    parser.add_argument("-m", "--model", required=True, help="Path to Onnx model file")
    #
    parser.add_argument("-s", "--speaker", type=int, help="Id of speaker (default: 0)")
    parser.add_argument(
        "--length-scale", "--length_scale", type=float, help="Phoneme length"
    )
    parser.add_argument(
        "--noise-scale", "--noise_scale", type=float, help="Generator noise"
    )
    parser.add_argument(
        "--noise-w-scale",
        "--noise_w_scale",
        "--noise-w",
        "--noise_w",
        type=float,
        help="Phoneme width noise",
    )
    #
    parser.add_argument("--cuda", action="store_true", help="Use GPU")
    #
    parser.add_argument(
        "--sentence-silence",
        "--sentence_silence",
        type=float,
        default=0.0,
        help="Seconds of silence after each sentence",
    )
    #
    parser.add_argument(
        "--data-dir",
        "--data_dir",
        action="append",
        default=[],
        help=(
            "Data directory to check for downloaded models "
            "(default: current directory, see option `--[no-]cwd-data-dir`). "
            "Environment variable syntax: "
            "One or more paths joined by `:`."
        ),
    )
    parser.add_argument(
        "--cwd-data-dir",
        default=True,
        action=argparse.BooleanOptionalAction,
        help=(
            "Use the current working directory as first data directory. "
            "See `--data-dir`. "
            "Environment variable syntax: "
            "Only `True` (case-insensitive) is allowed."
        )
    )
    parser.add_argument(
        "--download-dir",
        "--download_dir",
        help="Path to download voices (default: first data dir)",
    )
    #
    parser.add_argument(
        "--debug", action="store_true", help="Print DEBUG messages to console"
    )
    return parser


def main() -> None:
    """Run HTTP server."""

    parser = create_argument_parser()
    args = parser.parse_args()
    app_args = _argparse_namespace_to_app_args(args)
    app = create_app(app_args)
    app.run(host=args.host, port=args.port)


@dataclass
class _EnvVarInfo:
    option_string: str
    action: argparse.Action


_supported_explicit_action_types: List[int | str | None] = [None, 1, argparse.OPTIONAL, argparse.ZERO_OR_MORE, argparse.ONE_OR_MORE]


# `dest` of `argparse` `Action`s that should be split to a list.
_list_var_names = ["data_dir"]


def parse_true_bool(value: str) -> bool:
    if value.lower() == "true":
        return True
    else:
        raise ValueError(
            "Unsupported string value for flag. "
            "Only `True` (case-insensitive) is allowed."
        )


def create_environment_fallback_argument_parser(*args: Any, env_prefix: str = "", get_env: GetEnvType = getenv, formatter_class: type[argparse.HelpFormatter] | None = None, **kwargs: Any):
    def option_string_to_env_var_name(option_string: str) -> str:
        return env_prefix + option_string.lstrip("-").replace("-", "_").upper()

    def get_env_var_names(action: argparse.Action) -> List[tuple[str, str]]:
        return list({
            option_string_to_env_var_name(option_string): option_string
            for option_string in action.option_strings
            if option_string.startswith("--")
        }.items())

    # `ArgumentParser` needs to be initialized with the formatter class.
    # The class definition needs to reference the `env_prefix`.
    # Here this is achieved indirectly via closures.
    class EnvironmentFallbackHelpFormatter(argparse.ArgumentDefaultsHelpFormatter):
        def _get_help_string(self, action: argparse.Action) -> str | None:
            help = super()._get_help_string(action)
            if action.dest != 'help':
                env_var_names = get_env_var_names(action)
                if env_var_names:
                    info = f"[Environment variable{
                        "s" if len(env_var_names) > 1 else ""
                    }: {", ".join([name for name, _ in env_var_names])}]"
                    return info if help is None else f"{help} {info}"
            return help

    resolved_formatter_class = formatter_class or EnvironmentFallbackHelpFormatter

    class EnvironmentFallbackArgumentParser(argparse.ArgumentParser):
        def __init__(self):
            super().__init__(*args, formatter_class=resolved_formatter_class, **kwargs)

        # This method gets called by several other methods of the base class.
        def _parse_known_args(self, arg_strings: List[str], *args: Any, **kwargs: Any) -> tuple[argparse.Namespace, list[str]]:
            return super()._parse_known_args(self._get_env_args() + arg_strings, *args, **kwargs)

        def _get_env_args(self) -> List[str]:
            """Create CLI arguments for set environment variables."""

            # Create env var names from double-dash option strings.
            env_var_names: Dict[str, _EnvVarInfo] = {}
            for action in self._actions:
                for env_var_name, option_string in get_env_var_names(action):
                    env_var_names.setdefault(env_var_name, _EnvVarInfo(option_string, action))

            result: List[str] = []
            for (env_var_name, env_var_info) in env_var_names.items():
                try:
                    env_var_value=get_env(env_var_name)
                    if env_var_value is None:
                        continue
                    action = env_var_info.action
                    nargs = action.nargs
                    # If CLI arg supports a single value...
                    if nargs in _supported_explicit_action_types:
                        if action.dest in _list_var_names:
                            for part in env_var_value.split(":"):
                                result.append(f"{env_var_info.option_string}={part}")
                        else:
                            result.append(f"{env_var_info.option_string}={env_var_value}")
                    # If CLI arg is a flag without value...
                    elif nargs == 0:
                        if parse_true_bool(env_var_value):
                            result.append(f"{env_var_info.option_string}")
                    # If it's unclear what to do...
                    else:
                        raise ValueError("Unsupported argparse option type - not sure what to do.")
                except Exception as cause:
                    raise Exception(f"Error processing env var {env_var_name}.") from cause
            return result

    return EnvironmentFallbackArgumentParser()


@dataclass
class AppArgs:
    model: str
    speaker: Optional[int]
    length_scale: Optional[float]
    noise_scale: Optional[float]
    noise_w_scale: Optional[float]
    cuda: bool
    sentence_silence: float
    data_dir: list[str]
    download_dir: Optional[str]
    debug: bool


def _argparse_namespace_to_app_args(args: argparse.Namespace) -> AppArgs:
    special_args = ["host", "port", "cwd_data_dir", "data_dir"]
    app_args_params = {
        k: v for k, v in args.__dict__.items() if k not in special_args
    }
    return AppArgs(
        **app_args_params,
        data_dir=([str(Path.cwd())] if args.cwd_data_dir else []) + args.data_dir
    )


def create_app(args: AppArgs) -> Flask:
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO)
    _LOGGER.debug(args)

    if not args.download_dir:
        # Download voices to first data directory if not specified
        args.download_dir = args.data_dir[0]

    download_dir = Path(args.download_dir)

    # Download voice if file doesn't exist
    model_path = Path(args.model)
    if not model_path.exists():
        # Look in data directories
        voice_name = args.model
        for data_dir in args.data_dir:
            maybe_model_path = Path(data_dir) / f"{voice_name}.onnx"
            _LOGGER.debug("Checking '%s'", maybe_model_path)
            if maybe_model_path.exists():
                model_path = maybe_model_path
                break

    if not model_path.exists():
        raise ValueError(
            f"Unable to find voice: {model_path} (use piper.download_voices)"
        )

    default_model_id = model_path.name.rstrip(".onnx")

    # Load voice
    default_voice = PiperVoice.load(model_path, use_cuda=args.cuda)
    loaded_voices: Dict[str, PiperVoice] = {default_model_id: default_voice}

    # Create web server
    app = Flask(__name__)

    @app.route("/voices", methods=["GET"])
    def app_voices() -> Dict[str, Any]:
        """List downloaded voices.

        Outputs a JSON object with the format:
        {
          "<voice name>": { <voice config> },
          ...
        }

        for each voice in your data directories.
        """
        voices_dict: Dict[str, Any] = {}
        config_paths: List[Path] = [Path(f"{model_path}.json")]

        for data_dir in args.data_dir:
            for onnx_path in Path(data_dir).glob("*.onnx"):
                config_path = Path(f"{onnx_path}.json")
                if config_path.exists():
                    config_paths.append(config_path)

        for config_path in config_paths:
            model_id = config_path.name.rstrip(".onnx.json")
            if model_id in voices_dict:
                continue

            with open(config_path, "r", encoding="utf-8") as config_file:
                voices_dict[model_id] = json.load(config_file)

        return voices_dict

    @app.route("/all-voices", methods=["GET"])
    def app_all_voices() -> Dict[str, Any]:
        """List all Piper voices.

        Outputs voices.json from the piper-voices repo on HuggingFace.
        See: https://huggingface.co/rhasspy/piper-voices
        """
        with urlopen(VOICES_JSON) as response:
            return json.load(response)

    @app.route("/download", methods=["POST"])
    def app_download() -> str:
        """Download a voice.

        Downloads the .onnx and .onnx.json file from piper-voices repo on HuggingFace.
        See: https://huggingface.co/rhasspy/piper-voices

        Expects a JSON object with the format:
        {
          "voice": "<voice name>",   (required)
          "force_redownload": false  (optional)
        }

        Returns the name of the voice.
        Voice format must be <language>-<name>-<quality> like "en_US-lessac-medium".
        """
        data = json.loads(request.data)
        model_id = data.get("voice")
        if not model_id:
            raise ValueError("voice is required")

        force_redownload = data.get("force_redownload", False)
        download_voice(model_id, download_dir, force_redownload=force_redownload)

        return model_id

    @app.route("/", methods=["POST"])
    def app_synthesize() -> bytes:
        """Synthesize audio from text.

        Expects a JSON object with the format:
        {
          "text": "Text to speak.",      (required)
          "voice": "<voice name>",       (optional)
          "speaker": "<speaker name>",   (optional)
          "speaker_id": "<speaker id>",  (optional, overrides speaker)
          "length_scale": 1.0,           (optional)
          "noise_scale": 0.667,          (optional)
          "length_w_scale": 0.8          (optional)
        }
        """
        data = json.loads(request.data)
        text = data.get("text", "").strip()
        if not text:
            raise ValueError("No text provided")

        _LOGGER.debug(data)

        model_id = data.get("voice", default_model_id)
        voice = loaded_voices.get(model_id)
        if voice is None:
            for data_dir in args.data_dir:
                maybe_model_path = Path(data_dir) / f"{model_id}.onnx"
                if maybe_model_path.exists():
                    _LOGGER.debug("Loading voice %s", model_id)
                    voice = PiperVoice.load(maybe_model_path, use_cuda=args.cuda)
                    loaded_voices[model_id] = voice
                    break

        if voice is None:
            _LOGGER.warning("Voice not found: %s. Using default voice.", model_id)
            voice = default_voice

        speaker_id: Optional[int] = data.get("speaker_id")
        if (voice.config.num_speakers > 1) and (speaker_id is None):
            speaker = data.get("speaker")
            if speaker:
                speaker_id = voice.config.speaker_id_map.get(speaker)

            if speaker_id is None:
                _LOGGER.warning(
                    "Speaker not found: '%s' in %s",
                    speaker,
                    voice.config.speaker_id_map.keys(),
                )
                speaker_id = args.speaker or 0

        if (speaker_id is not None) and (speaker_id > voice.config.num_speakers):
            speaker_id = 0

        syn_config = SynthesisConfig(
            speaker_id=speaker_id,
            length_scale=float(
                data.get(
                    "length_scale",
                    (
                        args.length_scale
                        if args.length_scale is not None
                        else voice.config.length_scale
                    ),
                )
            ),
            noise_scale=float(
                data.get(
                    "noise_scale",
                    (
                        args.noise_scale
                        if args.noise_scale is not None
                        else voice.config.noise_scale
                    ),
                )
            ),
            noise_w_scale=float(
                data.get(
                    "noise_w_scale",
                    (
                        args.noise_w_scale
                        if args.noise_w_scale is not None
                        else voice.config.noise_w_scale
                    ),
                )
            ),
        )

        _LOGGER.debug("Synthesizing text: '%s' with config=%s", text, syn_config)
        with io.BytesIO() as wav_io:
            wav_file: wave.Wave_write = wave.open(wav_io, "wb")
            with wav_file:
                wav_params_set = False
                for i, audio_chunk in enumerate(voice.synthesize(text, syn_config)):
                    if not wav_params_set:
                        wav_file.setframerate(audio_chunk.sample_rate)
                        wav_file.setsampwidth(audio_chunk.sample_width)
                        wav_file.setnchannels(audio_chunk.sample_channels)
                        wav_params_set = True

                    if i > 0:
                        wav_file.writeframes(
                            bytes(
                                int(
                                    voice.config.sample_rate * args.sentence_silence * 2
                                )
                            )
                        )

                    wav_file.writeframes(audio_chunk.audio_int16_bytes)

            return wav_io.getvalue()

    return app


def create_app_args_from_env(get_env: GetEnvType = getenv) -> AppArgs:
    argument_parser = create_argument_parser(get_env=get_env)
    # Load arguments exclusively from environment variables.
    args, _ = argument_parser.parse_known_args([])
    return _argparse_namespace_to_app_args(args)


def create_app_from_env() -> Flask:
    return create_app(create_app_args_from_env())


if __name__ == "__main__":
    main()
