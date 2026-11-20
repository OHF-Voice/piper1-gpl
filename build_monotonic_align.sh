#!/usr/bin/env bash
set -eo pipefail

this_dir="$( cd "$( dirname "$0" )" && pwd )"

if [ -d "${this_dir}/.venv" ]; then
    source "${this_dir}/.venv/bin/activate"
fi

cd "${this_dir}/src/piper_tts/train/vits/monotonic_align"
mkdir -p monotonic_align
rm -f core.c
cythonize -i core.pyx
mv core*.so monotonic_align/
