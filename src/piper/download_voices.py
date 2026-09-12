"""Command-line utility for downloading Piper voices."""

import argparse
import json
import logging
import re
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import urlopen, urlretrieve

URL_FORMAT = "https://huggingface.co/rhasspy/piper-voices/resolve/main/{lang_family}/{lang_code}/{voice_name}/{voice_quality}/{lang_code}-{voice_name}-{voice_quality}{extension}?download=true"
VOICES_JSON = (
    "https://huggingface.co/rhasspy/piper-voices/resolve/main/voices.json?download=true"
)
VOICE_PATTERN = re.compile(
    r"^(?P<lang_family>[^-]+)_(?P<lang_region>[^-]+)-(?P<voice_name>[^-]+)-(?P<voice_quality>.+)$"
)

_LOGGER = logging.getLogger(__name__)


def main() -> None:
    """Download Piper voices."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "voice", nargs="*", help="Name of voice like 'en_US-lessac-medium'"
    )
    parser.add_argument(
        "--download-dir",
        "--download_dir",
        "--data-dir",
        "--data_dir",
        help="Directory to download voices into (default: current directory)",
    )
    parser.add_argument(
        "--force-redownload",
        "--force_redownload",
        action="store_true",
        help="Force redownloading of voice files even if they exist already",
    )
    parser.add_argument(
        "--debug", action="store_true", help="Print DEBUG logs to console"
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO)

    if not args.voice:
        list_voices()
        return

    if args.download_dir:
        download_dir = Path(args.download_dir)
    else:
        download_dir = Path.cwd()

    download_dir.mkdir(parents=True, exist_ok=True)

    for voice in args.voice:
        download_voice(voice, download_dir, force_redownload=args.force_redownload)


# -----------------------------------------------------------------------------


def list_voices() -> None:
    """List available voices and exit."""
    _LOGGER.debug("Downloading voices.json file: '%s'", VOICES_JSON)
    with urlopen(VOICES_JSON) as response:
        voices_dict = json.load(response)

    for voice in sorted(voices_dict.keys()):
        print(voice)


def download_voice(
    voice: str, download_dir: Path, force_redownload: bool = False
) -> None:
    """Download a voice model and config file to a directory."""
    voice = voice.strip()
    voice_match = VOICE_PATTERN.match(voice)
    if not voice_match:
        raise ValueError(
            f"Voice '{voice}' did not match pattern: <language>-<name>-<quality> like 'en_US-lessac-medium'",
        )

    lang_family = voice_match.group("lang_family")
    lang_code = lang_family + "_" + voice_match.group("lang_region")
    voice_name = voice_match.group("voice_name")
    voice_quality = voice_match.group("voice_quality")

    voice_code = f"{lang_code}-{voice_name}-{voice_quality}"
    format_args = {
        "lang_family": lang_family,
        "lang_code": lang_code,
        "voice_name": voice_name,
        "voice_quality": voice_quality,
    }

    files_to_download = []
    for extension in (".onnx", ".onnx.json"):
        path = download_dir / f"{voice_code}{extension}"
        if force_redownload or _needs_download(path):
            files_to_download.append((extension, path))

    if files_to_download:
        with TemporaryDirectory(dir=download_dir) as temp_dir:
            temp_path = Path(temp_dir)
            for extension, path in files_to_download:
                file_url = URL_FORMAT.format(extension=extension, **format_args)
                file_type = "model" if extension == ".onnx" else "config"
                _LOGGER.debug(
                    "Downloading %s from '%s' to '%s'", file_type, file_url, path
                )
                # urlretrieve checks Content-Length when the server supplies it.
                urlretrieve(file_url, temp_path / path.name)

            # Keep existing files intact until every download has succeeded.
            for _, path in files_to_download:
                (temp_path / path.name).replace(path)
                _LOGGER.debug("Downloaded: '%s'", path)

    _LOGGER.info("Downloaded: %s", voice)


def _needs_download(path: Path) -> bool:
    """Return True if file needs to be downloaded."""
    if not path.exists():
        return True

    if path.stat().st_size == 0:
        # Empty
        return True

    return False


# -----------------------------------------------------------------------------

if __name__ == "__main__":
    main()
