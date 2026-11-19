# ⚖️ Voice licensing

This page is the Piper project's standing answer to questions about voice model
licensing, especially for commercial use and redistribution. It is not legal
advice, and nobody involved in Piper is a lawyer.

## The short version

* The Piper **engine** is GPL-3.0-or-later. That is a real license grant from
  this project, and it covers the code in this repository.
* The Piper project makes **no license grant of its own over voice models**, and
  adds no restriction of its own either. Whatever rights you have in a voice
  come from that voice's training data and from the person who trained it.
* Each voice ships a `MODEL_CARD`. The `License` line on it names the license of
  **that voice's own dataset only** — not the datasets of any voice it was
  fine-tuned from.
* Whether a trained model is a derivative work of its training corpus is an
  unsettled legal question. **Piper takes no position on it.** That
  determination is yours to make, and for anything commercial you should make it
  with a lawyer rather than with us.

## Reading a MODEL_CARD

A `MODEL_CARD` has two sections that matter here:

```
## Dataset

* URL: https://datashare.ed.ac.uk/handle/10283/3443
* License: https://creativecommons.org/licenses/by/4.0/

## Training

Finetuned from U.S. English lessac voice (medium quality).
```

The `License` line describes the recordings listed directly above it, and
nothing else. It is **not** a statement about the weights, and it is **not** a
grant from the Piper project.

The `Training` line is the part people miss. Most Piper voices are fine-tuned
from another voice rather than trained from scratch, so a voice can carry
obligations from a corpus its own card never names. To see the full picture you
have to walk the chain: read the `Training` line, open the `MODEL_CARD` of the
voice it names, and repeat until you reach one that says "Trained from scratch."

Every dataset license in that chain is potentially relevant to you. Some of them
are restrictive.

## If you redistribute voices

Shipping `.onnx` files to end users is redistribution, not just use, and it is
the case people most often get wrong.

The `.onnx.json` config and `voices.json` carry **no licensing or provenance
information at all**. If you repackage Piper voices — directly, or by mirroring
someone else's packaged copies — carry the `MODEL_CARD` with each voice.
Dropping it strips the only licensing information that exists.

## The lessac base voice

The most common case by far. `en_US-lessac-medium` was trained on the
[Lessac Blizzard 2013 corpus][blizzard], whose license limits use to "research
and exploration of speech technologies" and excludes commercial use of the
resulting synthesis. A large share of the voices in `piper-voices` are
fine-tuned from it, directly or through an intermediate voice.

The Piper project holds no permission from Lessac Technologies or CSTR, and makes
no representation about rights flowing from those recordings. If you need
commercial or redistribution rights for a lessac-derived voice, that is an
agreement you would have to reach with them. We distribute these models on the
same no-representation basis.

## The replacement base voices

New voices, and lessac-derived voices being retrained, are fine-tuned from one
of two bases. Both were trained from scratch, so neither descends from lessac:

| Base | Recordings | License |
| ---- | ---------- | ------- |
| `nl_BE-rdh-medium` | [rdh][rdh], one Flemish male speaker | CC0 |
| `en_US-hifi_tts_92-medium` | Reader 92 (Cori Samuel) of [Hi-Fi TTS][hifi-tts] | CC BY 4.0 |

rdh is the default base. Despite being a Dutch voice, it fine-tunes well into
other languages. Voices with a higher-pitched speaker are fine-tuned from
hifi_tts_92 instead, because rdh tends to leave artifacts on them.

A voice's `MODEL_CARD` names its base in the `Training` section. hifi_tts_92 is
CC BY, so it carries an attribution requirement into every voice fine-tuned
from it.

The retrained voices keep their old names. A copy downloaded before a voice was
retrained is still the lessac-derived version, so check the `MODEL_CARD` of the
copy you actually have. [Commercial use](COMMERCIAL_USE.md) lists the voices
whose whole chain is on permissively licensed recordings.

Retraining is ongoing. If a particular language matters to you, open a
discussion on [piper-voices][piper-voices] and ask.

<!-- Links -->
[blizzard]: https://www.cstr.ed.ac.uk/projects/blizzard/2013/lessac_blizzard2013/license.html
[rdh]: https://github.com/r-dh/dutch-vl-tts
[hifi-tts]: https://www.openslr.org/109/
[piper-voices]: https://huggingface.co/rhasspy/piper-voices/discussions
