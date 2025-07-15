# 🛠️ Building Manually

We use [scikit-build-core](https://github.com/scikit-build/scikit-build-core) along with [cmake](https://cmake.org/) to build a Python module that directly embeds [espeak-ng][].

You will need the following system packages installed (`apt-get`):

* `build-essential`
* `cmake`
* `ninja-build`

To create a dev environment:

``` sh
git clone https://github.com/OHF-voice/piper1-gpl.git
cd piper1-gpl
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .[dev]
```

Next, run `script/dev_build` or manually build the extension:

``` sh
python3 setup.py build_ext --inplace
```

Now you should be able to use `script/run` or manually run Piper:

``` sh
python3 -m piper --help
```

You can manually build wheels with:

``` sh
python3 -m build
```

## Design Decisions

[espeak-ng][] is used via a small Python bridge in `espeakbridge.c` which uses Python's [limited API][limited-api]. This allows the use of Python's [stable ABI][stable-abi], which means Piper wheels only need to be built once for each platform (Linux, Mac, Windows) instead of for each platform **and** Python version.

We build upstream [espeak-ng][] since they added the `espeak_TextToPhonemesWithTerminator` that Piper depends on. This function gets phonemes for text as well as the "terminator" that ends each text clause, such as a comma or period. Piper requires this terminator because punctuation is passed on to the voice model as "phonemes" so they can influence synthesis. For example, a voice trained with statements (ends with "."), questions (ends with "?"), and exclamations (ends with "!") may pronounce sentences ending in each punctuation mark differently. Commas, colons, and semicolons are also useful for proper pauses in synthesized audio.

<!-- Links -->
[espeak-ng]: https://github.com/espeak-ng/espeak-ng
[limited-api]: https://docs.python.org/3/c-api/stable.html#limited-c-api
[stable-abi]: https://docs.python.org/3/c-api/stable.html#stable-abi
