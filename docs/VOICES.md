# 🗣️ Voices

[Listen to voice samples](https://rhasspy.github.io/piper-samples)

[Download voices](https://huggingface.co/rhasspy/piper-voices/tree/main)

Supported languages:

* العربية, Jordan (Arabic, ar_JO)
* Català, Spain (Catalan, ca_ES)
* Čeština, Czech Republic (Czech, cs_CZ)
* Cymraeg, Great Britain (Welsh, cy_GB)
* Dansk, Denmark (Danish, da_DK)
* Deutsch, Germany (German, de_DE)
* Ελληνικά, Greece (Greek, el_GR)
* English, Great Britain (English, en_GB)
* English, United States (English, en_US)
* Español, Argentina (Spanish, es_AR)
* Español, Spain (Spanish, es_ES)
* Español, Mexico (Spanish, es_MX)
* فارسی, Iran (Farsi, fa_IR)
* Suomi, Finland (Finnish, fi_FI)
* Français, France (French, fr_FR)
* Magyar, Hungary (Hungarian, hu_HU)
* íslenska, Iceland (Icelandic, is_IS)
* Italiano, Italy (Italian, it_IT)
* ქართული ენა, Georgia (Georgian, ka_GE)
* қазақша, Kazakhstan (Kazakh, kk_KZ)
* Lëtzebuergesch, Luxembourg (Luxembourgish, lb_LU)
* Latviešu, Latvia (Latvian, lv_LV)
* മലയാളം, India (Malayalam, ml_IN)
* हिंदी, India (Hindi, hi_IN)
* नेपाली, Nepal (Nepali, ne_NP)
* Nederlands, Belgium (Dutch, nl_BE)
* Nederlands, Netherlands (Dutch, nl_NL)
* Norsk, Norway (Norwegian, no_NO)
* Polski, Poland (Polish, pl_PL)
* Português, Brazil (Portuguese, pt_BR)
* Português, Portugal (Portuguese, pt_PT)
* Română, Romania (Romanian, ro_RO)
* Русский, Russia (Russian, ru_RU)
* Slovenčina, Slovakia (Slovak, sk_SK)
* Slovenščina, Slovenia (Slovenian, sl_SI)
* srpski, Serbia (Serbian, sr_RS)
* Svenska, Sweden (Swedish, sv_SE)
* Kiswahili, Democratic Republic of the Congo (Swahili, sw_CD)
* Türkçe, Turkey (Turkish, tr_TR)
* украї́нська мо́ва, Ukraine (Ukrainian, uk_UA)
* Tiếng Việt, Vietnam (Vietnamese, vi_VN)
* 简体中文, China (Chinese, zh_CN)

## Models

Voices are trained with [VITS](https://github.com/jaywalnut310/vits/) and exported to the [onnxruntime](https://onnxruntime.ai/).
You will need two files per voice:

1. A `.onnx` model file, such as [`en_US-lessac-medium.onnx`](https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/lessac/medium/en_US-lessac-medium.onnx)
2. A `.onnx.json` config file, such as [`en_US-lessac-medium.onnx.json`](https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json)

The `MODEL_CARD` file for each voice contains important licensing information. Piper is intended for personal use and text to speech research only; we do not impose any additional restrictions on voice models. Some voices may have restrictive licenses, however, so please review them carefully!

