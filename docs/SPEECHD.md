# 🗣️ Screen readers (Speech Dispatcher)

Piper can be used as a [Speech Dispatcher][speechd] output module, which makes it
available to screen readers (Orca, NVDA over a bridge, `spd-say`, Firefox reader
mode, Okular, ...).

Screen reading has requirements that a "synthesize a WAV file" pipeline cannot
meet:

| Requirement | How it is solved |
| --- | --- |
| No warm-up per utterance | [`piper.http_server`](API_HTTP.md) keeps the voice model in memory |
| Speech must start immediately | The server streams audio while synthesizing, and text is split into small chunks ([chunking](#chunking)) |
| Speech must stop immediately | `POST /stop`, connection close, or a new request on the same channel aborts inference *and* playback |
| Voice/rate from the screen reader | The output module maps Speech Dispatcher parameters to Piper's |

Two integrations are provided:

* **[Native output module](#native-module-recommended)** (`sd_piper`): speaks the
  Speech Dispatcher module protocol, so `STOP`, `CANCEL` and `PAUSE` really
  interrupt speech, and index marks are reported. **Recommended.**
* **[Generic module](#generic-module)** (`piper-client` + `sd_generic`): a single
  shell command per utterance. Simpler, less responsive.

---

## 1. Start the server

Install the HTTP extra and download a voice:

``` sh
python3 -m pip install 'piper-tts[http]'
python3 -m piper.download_voices en_US-kristin-medium
```

Run the server (it warms the model up at startup, so the first utterance is not
slower than the others):

``` sh
python3 -m piper.http_server -m en_US-kristin-medium --chunk-profile responsive
```

Check it:

``` sh
curl -s localhost:5000/info | python3 -m json.tool
piper-client "Piper is running."
```

### Run it as a user service

`sd_piper` writes a unit for the voice in your module configuration:

``` sh
sd_piper --print-service > ~/.config/systemd/user/piper-server.service
systemctl --user daemon-reload
systemctl --user enable --now piper-server
```

This is the recommended setup: the server is up before the first utterance,
systemd restarts it if it dies, and it stops at logout.

The generated unit backs off between restarts (2 s, 5 s, 11 s, 26 s, 60 s) and
gives up after five failures, so a mistake that cannot be fixed by restarting —
a voice that is not downloaded, typically — is reported once instead of looping:

``` sh
systemctl --user status piper-server     # "failed" instead of restarting forever
journalctl --user -u piper-server -n 30  # why it failed
systemctl --user reset-failed piper-server && systemctl --user start piper-server
```

If you write the unit yourself, remember that systemd expands neither `~` nor
`$PATH`: `ExecStart` needs absolute paths (`sd_piper --print-service` does this
for you).

You do not have to run a service at all, though — see [starting the server on
demand](#starting-the-server-on-demand).

---

## 2. Native module (recommended)

Install the module binary and its configuration (no root needed):

``` sh
mkdir -p ~/.local/libexec/speech-dispatcher-modules ~/.config/speech-dispatcher/modules
ln -sf "$(command -v sd_piper)" ~/.local/libexec/speech-dispatcher-modules/sd_piper
sd_piper --print-config > ~/.config/speech-dispatcher/modules/piper.conf
```

Speech Dispatcher discovers every `sd_<name>` binary in that directory, so the
module is registered as `piper` with `piper.conf` as its configuration. No
`speechd.conf` change is required. If you prefer to be explicit, add:

```
AddModule "piper" "sd_piper" "piper.conf"
DefaultModule piper
```

Restart the daemon and test:

``` sh
systemctl --user restart speech-dispatcher   # or: pkill speech-dispatcher
spd-say -O                                   # list output modules: "piper"
spd-say -o piper "Hello from Piper."
spd-say -o piper -r 50 "Now a little faster."
```

Set Piper as the default voice in your screen reader (Orca: *Preferences →
Voice → Speech system/synthesizer*) or make it the default module with
`DefaultModule piper` in `~/.config/speech-dispatcher/speechd.conf`.

### What the module supports

| Speech Dispatcher | Piper |
| --- | --- |
| `SET RATE` (-100..100) | `length_scale`, scaled by `PiperRateFactor` (rate 100 = 3x faster by default) |
| `SET VOLUME` (-100..100) | audio multiplier (100 = unchanged) |
| `SET VOICE` (`FEMALE1`, ...) + `SET LANGUAGE` | voice chosen from the `AddVoice` table |
| `SET SYNTHESIS_VOICE` | Piper voice name, used as-is |
| `LIST VOICES` | `AddVoice` entries plus every voice the server reports |
| `STOP` / `CANCEL` | playback killed, inference abandoned, `703 STOP` |
| `PAUSE` | treated as a stop (`704 PAUSE`); Piper has no resume position |
| `CHAR`, `KEY` | spoken as a single chunk |
| index marks | reported as each chunk of text is played |
| `SET PITCH` | not supported by Piper voices (ignored) |
| `SOUND_ICON` | not supported (Speech Dispatcher falls back) |

Audio can be played by the module (default) or handed back to Speech Dispatcher:

```
PiperAudio player   # this module plays: interruption drops buffered audio at once
PiperAudio server   # speech-dispatcher plays, using AudioOutputMethod
```

`player` is the default because it gives the crispest interruption: the player
process is killed, so nothing that was already buffered is heard.

Logs go to `~/.cache/speech-dispatcher/log/piper.log`.

### Starting the server on demand

If nothing answers at `PiperURL`, the module starts a server itself, so
`spd-say -o piper "hello"` works with no server running and no user service.
Only the first utterance waits (the time it takes to load the model).

```
PiperAutostart auto              # auto (default) | yes | no
PiperServerManager auto          # auto | systemd | process | none
PiperServerService "piper-server.service"
#PiperServerCommand "python3 -m piper.http_server -m /path/voice.onnx"
PiperServerTimeout 20
```

How it works, in order:

1. **`INIT` never waits.** Speech Dispatcher blocks while a module loads, so the
   server is started in the background; an utterance that arrives too early
   waits in the module's worker thread instead, and `STOP` still interrupts it.
2. **A server that already answers is reused** — nothing is started, and two
   module instances never start two servers: whoever starts one holds an
   advisory lock in `$XDG_RUNTIME_DIR` until it answers, and the others wait
   for it instead of starting their own.
3. **systemd first.** If the user unit named by `PiperServerService` exists, it
   is started (`systemctl --user start piper-server.service`). Otherwise the
   server is started as a transient unit (`systemd-run --user --collect
   --unit=piper-server-<port>`), so it is supervised by systemd, survives the
   module, and is cleaned up at logout. Without systemd, it is started as a
   detached process logging to `~/.local/state/piper/http_server.log`.
4. **The command** is `PiperServerCommand` (`~` is expanded), or, by default,
   derived from the configuration:
   `python3 -m piper.http_server --host 127.0.0.1 --port <PiperURL port> --model <DefaultVoice>`.
5. **Only local servers.** A remote `PiperURL` is never started, and a failed
   start is not retried for 30 s, so every utterance does not pay the timeout.

The started server keeps running after Speech Dispatcher exits: the next
session finds a warm model. Stop it with `systemctl --user stop
piper-server-5000` (transient unit), or set `PiperAutostart no` and manage it
yourself.

---

## 3. Generic module

If you would rather use the stock `sd_generic`:

``` sh
cp etc/speech-dispatcher/modules/piper-generic.conf ~/.config/speech-dispatcher/modules/
systemctl --user restart speech-dispatcher
spd-say -o piper-generic "Hello from the generic module."
```

It runs, for each utterance:

``` sh
echo "$DATA" | piper-client --voice "$VOICE" --rate $RATE --sd-volume $VOLUME
```

`piper-client` chunks the text, streams the audio from the server and plays it,
and stops playback immediately when Speech Dispatcher terminates it (SIGTERM).
Compared to the native module you lose index marks, `PAUSE`, and you pay one
process start (~50 ms) per utterance.

This replaces the older recipe of calling the `piper` CLI directly, which
reloaded the model for every utterance.

---

## 4. The command-line client

`piper-client` is also useful on its own:

``` sh
piper-client "Hello world."                       # play
echo "long text..." | piper-client                # from stdin
piper-client --output raw "Hi" | aplay -r 22050 -f S16_LE -t raw -
piper-client --stop                               # interrupt whatever is speaking
piper-client --info                               # server info
piper-client --list-voices
```

Useful options (all of them also read an environment variable, which is handy
inside a `GenericExecuteSynth` command):

| Option | Environment | Meaning |
| --- | --- | --- |
| `--url` | `PIPER_URL` | server URL (default `http://localhost:5000`) |
| `--voice` | `PIPER_VOICE`, `VOICE` | voice name (`no_voice` and `*.onnx` are handled) |
| `--rate` | `PIPER_RATE`, `RATE` | speech rate in [-100, 100] |
| `--rate-factor` | `PIPER_RATE_FACTOR` | how much `rate=100` speeds speech up (default 3) |
| `--length-scale` | `PIPER_LENGTH_SCALE` | phoneme length, overrides `--rate` |
| `--sd-volume` | `PIPER_VOLUME`, `VOLUME` | volume in [-100, 100] (100 = unchanged) |
| `--chunk-profile` | `PIPER_CHUNK_PROFILE` | `instant`, `responsive`, `balanced`, `smooth`, `off` |
| `--chunk-max-words` etc. | `PIPER_CHUNK_MAX_WORDS`, ... | individual chunking knobs |
| `--chunk-mode` | `PIPER_CHUNK_MODE` | `client` (default) or `server` |
| `--prefetch` | `PIPER_PREFETCH` | chunks synthesized ahead of playback |
| `--player` | `PIPER_PLAYER` | player command template, or `auto` |
| `--player-latency-ms` | `PIPER_PLAYER_LATENCY_MS` | playback buffer (default 40 ms) |
| `--channel` | `PIPER_CHANNEL` | preemption group on the server |

Example of a custom player (PipeWire, specific sink):

``` sh
piper-client --player "pw-play --raw --format=s16 --rate={rate} --channels=1 --latency={latency_ms}ms --target=my-sink -" "Hello."
```

A "read the selection aloud" hotkey becomes:

``` sh
xclip -o -selection primary | piper-client --channel hotkey
```

Press it again and the previous reading is interrupted automatically (same
channel).

---

## Chunking

Piper synthesizes one sentence at a time, so a long sentence means a long wait
before the first sound. The client (or the server) therefore splits text on
word, punctuation and sentence boundaries before synthesis.

Splitting is a trade-off: short chunks start faster, but prosody suffers and
boundary artifacts can appear. Nothing is hardcoded — pick a profile and adjust:

| Profile | First chunk | Chunks | First audio | Speech length | Use for |
| --- | --- | --- | --- | --- | --- |
| `instant` | 2 words | 3 words | 50 ms | +37% | slow machines, "what is under the cursor" |
| `responsive` | 3 words | 5 words | 132 ms | +18% | **default**, screen reading |
| `balanced` | 4 words | 10 words | ~150 ms | +10% | mixed reading |
| `smooth` | sentence | sentence | 135 ms | +0% | reading documents |
| `off` | — | — | 1030 ms | +0% | one request, one utterance |

(measured with `en_US-lessac-low` on a laptop CPU and a 30-word text; the
"speech length" column is the price of chunking: each chunk gets its own
sentence-like prosody, so more pauses are inserted.)

Individual knobs (`--chunk-max-words`, `PiperChunkMinWords`, `max_chars`,
`break_on_clause`, `abbreviations`, ...) are documented in
[`piper/chunking.py`](../src/piper/chunking.py) and accepted by the CLI, the
module config, and the HTTP API.

If you hear clicks at chunk boundaries, add a few milliseconds of silence
between chunks (`--chunk-silence 0.02` / `PiperChunkSilence 0.02`) or use a
larger profile.

Audio normalization is switched off automatically as soon as text is chunked:
normalizing each chunk to full scale makes the volume jump from chunk to chunk.
Use `--sd-volume` / `SET VOLUME` (or `PiperNormalize 1`, at the cost of that
pumping) if the result is too quiet.

---

## Latency checklist

1. **Server running before the screen reader** — otherwise the first utterance
   pays the model load (~1 s).
2. **Warm-up enabled** (default) — the first inference is the expensive one.
3. **Voice quality** — `low` and `medium` voices are much faster than `high`;
   for screen reading `medium` is usually the sweet spot.
4. **Chunk profile** — the single most effective knob for time-to-first-audio.
5. **Player latency** — 40 ms is a good default; increase it if audio breaks up.
6. **Rate** — a high rate shortens the audio, which also shortens synthesis.
7. Measure: `curl -s localhost:5000/info` reports `first_audio_seconds` for the
   last utterance.

---

## Troubleshooting

**"dummy" module speaks an error message**
Speech Dispatcher could not talk to the module. Check
`~/.cache/speech-dispatcher/log/piper.log` and that `sd_piper` is executable and
reachable through the symlink.

**No sound, no error**
Test the player alone:
`piper-client --output raw "test" | aplay -r 22050 -f S16_LE -t raw -`.
`pw-play` needs the trailing `-` to read stdin. In `player` mode the module
inherits the environment of `speech-dispatcher`, so `PULSE_SERVER`/`PULSE_SINK`
must be visible there.

**Speech does not stop**
With the native module, `STOP` kills the player process. If you configured
`PiperAudio server`, stopping is handled by Speech Dispatcher's audio layer
instead; try `PiperAudio player`.

**Speech is slow and low-pitched (or fast and high-pitched)**
That is an audio sample rate mismatch. Voices do not share one rate
(`fr_FR-tom-medium` is 44.1 kHz, `en_US-kristin-medium` 22.05 kHz); the module
and `piper-client` use the rate of the voice being spoken, so this should not
happen — check `curl -s localhost:5000/voices | grep -A2 sample_rate` and the
`X-Piper-Sample-Rate` header if it does.

**Speech is choppy**
Increase `PiperPlayerLatencyMs`, increase `PiperPrefetch`, use a smaller voice,
or a larger chunk profile.

**The module works but the screen reader still uses espeak**
The screen reader picks the module itself: set it in its preferences, or set
`DefaultModule piper` in `~/.config/speech-dispatcher/speechd.conf`.

<!-- Links -->
[speechd]: https://freebsoft.org/speechd
