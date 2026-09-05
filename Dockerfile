FROM python:3.12 AS builder

ARG lang=

RUN apt-get update && \
    apt-get install --yes --no-install-recommends \
      build-essential cmake ninja-build git

WORKDIR /app

COPY pyproject.toml setup.py CMakeLists.txt MANIFEST.in README.md ./
COPY src/piper/ ./src/piper/
COPY script/setup script/dev_build script/package ./script/
RUN script/setup --dev
RUN script/dev_build
RUN script/package

# -----------------------------------------------------------------------------

FROM python:3.12-slim

ARG lang=

ENV PIP_BREAK_SYSTEM_PACKAGES=1

WORKDIR /app
COPY --from=builder /app/dist/piper_tts-*linux*.whl ./dist/
RUN WHEEL=$(ls ./dist/piper_tts-*linux*.whl) && \
    pip3 install "$WHEEL[$(echo "${lang}" | tr -d ' ')]" 'flask>=3,<4'

COPY docker/entrypoint.sh /

EXPOSE 5000

ENTRYPOINT ["/entrypoint.sh"]
