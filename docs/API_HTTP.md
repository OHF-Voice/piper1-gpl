# 🌐 HTTP API

Install the necessary dependencies:

``` sh
python3 -m pip install piper-tts[http]
```

Download a voice, for example:

``` sh
python3 -m piper.download_voices en_US-lessac-medium
```

Run the web server:

``` sh
python3 -m piper.http_server -m en_US-lessac-medium
```

This will start an HTTP server on port 5000 (use `--host` and `--port` to override).
If you have voices in a different directory, use `--data-dir <DIR>`

The voice model is loaded once and stays in memory, and a warmup utterance is
synthesized at startup (disable with `--no-warmup`) so the first request is not
slower than the others.

Audio is **streamed while it is being synthesized**, and requests can be
**interrupted**, which is what makes the server usable as a screen reader
backend.

## Web Interface

Open [http://localhost:5000](http://localhost:5000) in your browser to test the voice:
enter some text, click **Speak**, and listen to the result. The page also shows
information about the voice (name, language, number of speakers) and, for the most
recently synthesized utterance, the synthesis time along with the phonemes and their
audio alignments.

The same information is available as JSON from the `/info` endpoint:

``` sh
curl localhost:5000/info
```

## Synthesizing Audio

Get WAV files via HTTP by posting to `/synthesize`:

``` sh
curl -X POST -H 'Content-Type: application/json' -d '{ "text": "This is a test." }' -o test.wav localhost:5000/synthesize
```

The JSON data fields are:

* `text` (required) - text to synthesize
* `voice` (optional) - name of voice to use; defaults to `-m <VOICE>`
* `speaker` (optional) - name of speaker for multi-speaker voices
* `speaker_id` (optional) - id of speaker for multi-speaker voices; overrides `speaker`
* `length_scale` (optional) - speaking speed; defaults to 1
* `noise_scale` (optional) - speaking variability
* `noise_w_scale` (optional) - phoneme width variability
* `volume` (optional) - audio multiplier; defaults to 1
* `normalize_audio` (optional) - scale samples to the full range; defaults to
  **false when the text is chunked** (normalizing each chunk separately makes the
  loudness jump between chunks) and to true otherwise. Force it with
  `--normalize` / `--no-normalize` on the server.
* `sentence_silence` (optional) - seconds of silence after each sentence
* `chunk_silence` (optional) - seconds of silence between chunks of a sentence
* `chunk` (optional) - chunking options, see [below](#chunking)
* `stream` (optional) - set to `false` for a buffered response with a complete
  WAV header (needed by `<audio>` elements); defaults to `true`
* `format` (optional) - `wav` (default) or `raw`
* `stream_id`, `group`, `channel`, `preempt` (optional) - see
  [interruption](#interruption)

The same fields can be passed as query parameters, and a plain text body is
accepted as `text`. `POST /` behaves like `POST /synthesize`.

Get the available voices with:

``` sh
curl localhost:5000/voices
```

## Streaming Audio

`POST /stream` returns raw 16-bit mono PCM as soon as the first piece of audio
exists, using chunked transfer encoding:

``` sh
curl -N -H 'Content-Type: application/json' \
    -d '{ "text": "This is a test." }' \
    localhost:5000/stream | aplay -r 22050 -f S16_LE -t raw -
```

The audio format is reported in the response headers:

* `X-Piper-Sample-Rate`, `X-Piper-Sample-Width`, `X-Piper-Channels`
* `X-Piper-Voice` - voice actually used
* `X-Piper-Stream-Id` - id needed to stop this stream

`POST /synthesize` streams too; it just prepends a WAV header whose length
fields are "big enough" so that players stream until end of data.

## Interruption

A screen reader must be able to silence the current utterance instantly when the
user moves to another area. Three mechanisms are available:

**1. Stop explicitly**

``` sh
curl -X POST -d '{}' localhost:5000/stop                          # everything
curl -X POST -d '{"stream_id": "abc"}' localhost:5000/stop        # one stream
curl -X POST -d '{"group": "utt-1"}' localhost:5000/stop          # one utterance
curl -X POST -d '{"channel": "screen-reader"}' localhost:5000/stop
```

Inference stops before the next chunk, the response ends, and the engine is
immediately free. The model stays loaded, so there is no warm-up afterwards.

**2. Close the connection** - a client that stops reading and closes the socket
also cancels the synthesis.

**3. Preemption** - a new request cancels the running ones in the same
`channel` (default: `default`). This is on by default; use `--no-preempt` on the
server or `"preempt": false` per request to disable it.

Requests that belong to the same utterance (a long text sent as several chunk
requests) must share a `group` so they do not cancel each other.

`/info` lists the streams currently active.

## Chunking

Piper synthesizes one sentence at a time, so a long sentence delays the first
sample. The server splits text on word/punctuation/sentence boundaries before
synthesis, which shortens time-to-first-audio and makes interruption faster.

Server defaults:

``` sh
python3 -m piper.http_server -m en_US-lessac-medium \
    --chunk-profile responsive \
    --chunk-max-words 5 --chunk-first-max-words 3 --chunk-min-words 2
```

Profiles: `instant`, `responsive` (default), `balanced`, `smooth`, `off`.

Per request:

``` sh
curl -N -d '{"text": "...", "chunk": {"max_words": 3, "first_max_words": 2}}' \
    localhost:5000/stream
curl -N -d '{"text": "...", "chunk": "smooth"}' localhost:5000/stream
curl -N -d '{"text": "...", "chunk": {"enabled": false}}' localhost:5000/stream
```

Clients that chunk the text themselves should send
`"chunk": {"enabled": false}` so the text is not split twice.

All available options are documented in
[`piper/chunking.py`](../src/piper/chunking.py).

Measured on one machine with `en_US-lessac-low` and a 30-word text, the effect on
time-to-first-audio is large:

| Chunking | First audio | Audio produced |
| --- | --- | --- |
| `off` | 1030 ms | 8.96 s |
| `smooth` | 135 ms | 8.88 s |
| `responsive` | 132 ms | 10.60 s |
| `instant` | 50 ms | 12.32 s |

Note the last column: the smaller the chunks, the more pauses are added and the
longer the speech becomes. That is the trade-off to tune.

## Endpoints

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/` | test page |
| `POST` | `/`, `/synthesize` | synthesize, streaming WAV |
| `POST` | `/stream` | synthesize, streaming raw PCM |
| `POST` | `/stop` | stop active streams |
| `GET` | `/info` | voice, chunking defaults, active streams, last utterance |
| `GET` | `/voices` | downloaded voices |
| `GET` | `/all-voices` | all Piper voices (from HuggingFace) |
| `POST` | `/download` | download a voice |
