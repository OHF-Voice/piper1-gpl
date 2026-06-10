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

Get the available voices with:

``` sh
curl localhost:5000/voices
```
