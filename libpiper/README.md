# Piper C API

A shared library for Piper with a C-style API.

See `piper.h` for details.

## Building

``` sh
cmake -Bbuild -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=$PWD/install
cmake --build build
cmake --install build
```

This will automatically download/build [espeak-ng][] as well as download shared libraries for the [onnxruntime][].

To use `libpiper`, you will need to:

* Include `piper.h` (`install/include/`)
* Link to the `libpiper` library (`install/`)
* Link to the `libonnxruntime` library (`install/lib/`)
* Provide `piper_create` with the path to espeak-ng's data (`install/espeak-ng-data/`)

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
    // joptions.speaker_id = 5;

    piper_synthesize_start(synth, "Welcome to the world of speech synthesis!",
                           &options /* NULL for defaults */);

    piper_audio_chunk chunk;
    while (piper_synthesize_next(synth, &chunk) != PIPER_DONE) {
        audio_stream.write(reinterpret_cast<const char *>(chunk.samples),
                           chunk.num_samples * sizeof(float));
    }

    piper_free(synth);

    return 0;
}
```

<!-- Links -->
[espeak-ng]: https://github.com/espeak-ng/espeak-ng
[onnxruntime]: https://github.com/microsoft/onnxruntime
