#!/usr/bin/env bash
VALID_COMMANDS=("speak" "download" "server")

DATA_DIR='/data'
COMMAND="$1"
shift

case "${COMMAND}" in
  speak)
    exec python3 -m piper_tts --data-dir "${DATA_DIR}" "$@"
    ;;
  download)
    exec python3 -m piper_tts.download_voices --data-dir "${DATA_DIR}" "$@"
    ;;
  server)
    exec python3 -m piper_tts.http_server --host 0.0.0.0 --data-dir "${DATA_DIR}" "$@"
    ;;
  ""|help|-h|--help)
    echo "Usage: <command> [args...]"
    echo "Available commands:"
    echo "  speak        Synthesize audio from text"
    echo "  download     Download voices"
    echo "  server       Run HTTP server"
    exit 0
    ;;
  *)
    echo "Error: Unknown command '$COMMAND'"
    echo "Run with --help for usage."
    exit 1
    ;;
esac
