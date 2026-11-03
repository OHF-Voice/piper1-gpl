# 🔧 Piper C/C++ API

A shared library for Piper with a C-style API.

See `piper.h` for details.

## Building

``` sh
cmake -B build -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=$PWD/install
cmake --build build --config Release
cmake --install build --config Release
```

On Windows in a `cmd` shell, use `%CD%` instead of `$PWD`:

``` bat
cmake -B build -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=%CD%/install
cmake --build build --config Release
cmake --install build --config Release
```

The `--config Release` flag is required for multi-config generators such as
Visual Studio and is ignored by single-config generators, so it is safe to
pass on every platform.

This will automatically download/build [espeak-ng][] as well as download shared libraries for the [onnxruntime][].

To use `libpiper`, you will need to:

* Include `piper.h` (`install/include/`)
* Link to the `libpiper` library (`install/lib/`)
* Link to the `libonnxruntime` library (`install/lib/`)
* Provide `piper_create` with the path to espeak-ng's data (`install/share/espeak-ng-data/`)

On Windows, the installed CLI and runtime DLLs are in `install/bin/`.
The CLI also has a copy of `espeak-ng-data` next to its executable, so it can
find its data without depending on the original build directory. The data in
`install/share/` remains available for C API callers.

``` bat
install\bin\piper_exe.exe --version
```

Target machines also need the [Microsoft Visual C++ Redistributable](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist)
appropriate for the compiler version and target architecture.

## Example

``` c++
#include <fstream>
#include <piper.h>

int main() {
    piper_synthesizer *synth = piper_create("/path/to/voice.onnx",
                                            "/path/to/voice.onnx.json",
                                            "/path/to/espeak-ng-data");

    // aplay -r 22050 -c 1 -f FLOAT_LE -t raw output.raw
    std::ofstream audio_stream("output.raw", std::ios::binary);

    piper_synthesize_options options = piper_default_synthesize_options(synth);
    // Change options here:
    // options.length_scale = 2;
    // options.speaker_id = 5;

    piper_synthesize_start(synth, "Welcome to the world of speech synthesis!",
                           &options /* NULL for defaults */);

    piper_audio_chunk chunk;
    auto status = PIPER_OK;
    do {
        status = piper_synthesize_next(synth, &chunk);
        audio_stream.write(reinterpret_cast<const char *>(chunk.samples),
                           chunk.num_samples * sizeof(float));
    } while (PIPER_OK == status);

    piper_free(synth);

    return 0;
}
```

## Streaming

`piper_synthesize_next` returns one chunk of audio per sentence. To get audio before the whole sentence is synthesized, split the voice into an encoder and a decoder (see [STREAMING.md](../docs/STREAMING.md)):

``` sh
python3 -m piper.split_voice_for_streaming /path/to/voice.onnx
```

`piper_create` picks up `voice.encoder.onnx` and `voice.decoder.onnx` automatically and then returns several smaller chunks per sentence.

<!-- Links -->
[espeak-ng]: https://github.com/espeak-ng/espeak-ng
[onnxruntime]: https://github.com/microsoft/onnxruntime
