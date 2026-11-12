# 💼 Commercial use

This page lists the Piper voices whose **entire training chain** uses recordings
whose licenses permit commercial use. It is a companion to
[Voice licensing](LICENSING.md); read that first. Everything said there still
applies:

* This is not legal advice, and nobody involved in Piper is a lawyer.
* The Piper project grants no license over voice models. A voice's rights come
  from its training data and from the person who trained it.
* Whether a trained model is a derivative work of its recordings is unsettled.
  **Piper takes no position on it.** This list only tells you which voices avoid
  restrictive datasets anywhere in their history, which is the question people
  usually mean when they ask "can I use this commercially?"

## How a voice gets on this list

A voice is listed when every dataset in its chain permits commercial use. The
chain is the voice's own dataset, plus the dataset of the voice it was
fine-tuned from, and so on back to a voice trained from scratch. Each one has
to be CC0, public domain, CC BY, CC BY-SA, Apache 2.0, or a custom license that
says commercial use is permitted.

Retraining does not change a voice's own dataset. For example,
`en_US-amy-medium` has been retrained away from lessac, but its recordings have
no documented license, so it is not listed. `en_US-hfc_female-medium` is
CC BY-NC-SA however it is trained.

## Check the copy you have

Many voices below were **retrained in late 2026** to remove a lessac base
from their chain. The voice name did not change. A copy downloaded before the
retrain is the old version and **does not qualify**, even though it has the
same file name.

The `MODEL_CARD` next to the voice says which version you have. For a voice in
the rdh or hifi_tts_92 tables, its `Training` section must name that base. If
it says "Finetuned from U.S. English lessac voice", download the voice again.

## Voices fine-tuned from rdh

[rdh][rdh] is a Flemish (nl_BE) male voice, trained from scratch on CC0
recordings. These voices' own datasets are CC0 as well, so nothing in the chain
asks anything of you.

| Voice | Dataset license |
| ----- | --------------- |
| `nl_BE-rdh-medium` (the base itself) | CC0 |
| `bg_BG-dimitar-medium` | CC0 |
| `de_DE-thorsten-medium` | CC0 |
| `en_US-joe-medium` | CC0 |
| `en_US-mike-medium` | CC0 |
| `es_ES-davefx-medium` | CC0 |
| `fi_FI-harri-medium` | CC0 |
| `hu_HU-imre-medium` | CC0 |
| `ne_NP-chitwan-medium` | CC0 |
| `nl_BE-flemishguy-medium` | CC0 |
| `nl_NL-alex-medium` | CC0 |
| `nl_NL-pim-medium` | CC0 |
| `nl_NL-ronnie-medium` | CC0 |
| `pl_PL-darkman-medium` | CC0 |
| `pt_BR-cadu-medium` | CC0 |
| `pt_BR-jeff-medium` | CC0 |
| `ro_RO-mihai-medium` | CC0 |
| `ru_RU-denis-medium` | CC0 |

Only the `medium` quality of these voices is listed. Other qualities of the
same voices, such as `de_DE-thorsten-high` and `fi_FI-harri-low`, still descend
from lessac or ryan.

## Voices fine-tuned from hifi_tts_92

`en_US-hifi_tts_92-medium` is trained from scratch on reader 92 (Cori Samuel)
of the [Hi-Fi Multi-Speaker English TTS dataset][hifi-tts], which is
**CC BY 4.0**. Every voice in this group therefore carries an attribution
requirement for Hi-Fi TTS, in addition to whatever its own dataset asks for.

| Voice | Dataset license | Notes |
| ----- | --------------- | ----- |
| `en_US-hifi_tts_92-medium` (the base itself) | CC BY 4.0 | |
| `cs_CZ-jirka-medium` | CC0 | `cs_CZ-jirka-low` still descends from lessac |
| `de_DE-kerstin-medium` | CC0 | |
| `en_GB-alba-medium` | CC BY 4.0 | |
| `en_GB-cori-medium` | CC BY 4.0 | Same reader and dataset as the base |
| `en_GB-jenny_dioco-medium` | [Custom][jenny] | Commercial use permitted; the voice must be called "Jenny", and "Jenny (Dioco)" where practical |
| `en_US-kathleen-medium` | CC0 | New quality; `en_US-kathleen-low` still descends from ryan |
| `es_ES-sharvard-medium` | CC BY 3.0 | |
| `fr_FR-siwis-medium` | CC BY 4.0 | |
| `hu_HU-anna-medium` | CC0 | |
| `hu_HU-berta-medium` | CC0 | |
| `pt_BR-faber-medium` | CC0 | |
| `ru_RU-dmitri-medium` | CC0 | |
| `sk_SK-lili-medium` | CC0 | |
| `zh_CN-chaowen-medium` | CC0 | |

## Voices trained from scratch

These voices have no base model, so only their own dataset matters.

| Voice | Dataset license |
| ----- | --------------- |
| `ca_ES-upc_ona-x_low` | CC BY-SA 3.0 ES |
| `ca_ES-upc_pau-x_low` | CC BY-SA 3.0 ES |
| `de_DE-mls-medium` | CC BY 4.0 |
| `el_GR-rapunzelina-medium` | CC0 |
| `en_GB-cori-high` | Public domain |
| `en_US-john-medium` | Public domain (fine-tuned from `en_US-kristin-medium`) |
| `en_US-kristin-medium` | Public domain |
| `en_US-libritts-high` | CC BY 4.0 |
| `en_US-ljspeech-high` | Public domain |
| `en_US-ljspeech-medium` | Public domain |
| `en_US-norman-medium` | Public domain |
| `es_ES-carlfm-x_low` | Public domain |
| `fr_FR-mls-medium` | CC BY 4.0 |
| `it_IT-serena-high` | CC BY 4.0 |
| `it_IT-serena-medium` | CC BY 4.0 |
| `kk_KZ-iseke-x_low` | CC BY 4.0 |
| `kk_KZ-issai-high` | CC BY 4.0 |
| `kk_KZ-raya-x_low` | CC BY 4.0 |
| `ne_NP-google-x_low` | CC BY-SA 4.0 |
| `nl_BE-nathalie-x_low` | CC0 |
| `nl_BE-rdh-x_low` | CC0 |
| `nl_NL-mls-medium` | CC BY 4.0 |
| `no_NO-nvcc-medium` | CC0 |
| `sv_SE-nst-medium` | CC0 |
| `uk_UA-lada-x_low` | Apache 2.0 |
| `uk_UA-ukrainian_tts-medium` | CC0 |

The English public-domain voices were trained by Bryce Beattie; their training
notes are on [his site][bryce].

## What the licenses ask of you

| License | What it asks |
| ------- | ------------ |
| CC0, public domain | Nothing. |
| CC BY | Credit the dataset (and, for the hifi_tts_92 group, the base's dataset too). The `MODEL_CARD` has the dataset URL to cite. |
| CC BY-SA | Credit, and anything you build from the dataset is shared under the same license. Whether that reaches a trained model, or audio it produces, is one of the open questions above. |
| Apache 2.0 | Keep the license and any notice with what you distribute. |

When you ship a voice, ship its `MODEL_CARD` with it. It is the only place the
licensing information lives (see [Voice licensing](LICENSING.md)).

## Not on this list

* **Everything fine-tuned from lessac or ryan.** That includes, through an
  intermediate voice, `eu_ES-antton` and `eu_ES-maider` (from amy), `es_MX-ald`
  (from the earlier davefx), `fa_IR-ganji` and `fa_IR-ganji_adabi` (from amir),
  `lt_LT-reginute1` and `lt_LT-ingute` (from irina), `sv_SE-lisa` (from
  talesyntese), and `de_DE-thorsten_emotional` (from the earlier thorsten).
  These voices are being retrained over time.
* **Non-commercial datasets**, whatever the base. Examples are hfc_female,
  hfc_male, ryan, semaine, l2arctic, saspeech, kss, hi_fi_captain, tsync2,
  lanfrica and xiao_ya.
* **Datasets with no documented license**, such as amy, irina and huayan.
* **Permissively licensed voices whose base is not documented.** Their own
  datasets allow commercial use, but their cards do not say whether they were
  trained from scratch. Ask the person who trained them:
  `cs_CZ-kasandra-medium`, `en_US-bryce-medium`, `es_AR-daniela-high`,
  `es_MX-claude-high`, `lv_LV-aivars-medium`, `sl_SI-artur-medium`,
  `te_IN-padmavathi-medium`, `te_IN-venkatesh-medium`, `uk_UA-mykyta-high`,
  `uk_UA-oleksa-high` and `uk_UA-tetiana-high`.
* **Voices whose card only says "See URL".** These have not been reviewed yet.
  Follow the link on the card and walk the chain yourself.

<!-- Links -->
[rdh]: https://github.com/r-dh/dutch-vl-tts
[hifi-tts]: https://www.openslr.org/109/
[jenny]: https://github.com/dioco-group/jenny-tts-dataset
[bryce]: https://brycebeattie.com/files/tts/
