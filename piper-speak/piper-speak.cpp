#include <fstream>
#include <piper.h>
#include <filesystem>
#include <iostream>

//our build system supplies us with 2 config paths
// BUILD_ENV_ESPEAK_EN_DATA holds espeak data for piper
// BUILD_ENV_VOICES_PATH holds a folder which contains voices

///returns the path to some voice's onnx file 
std::filesystem::path get_any_voice() {
    std::filesystem::path voice_dir = BUILD_ENV_VOICES_PATH;
    if (!std::filesystem::exists(voice_dir)) {
        std::cerr << "the voice directory (" << voice_dir << ") does not exist";
        std::exit(1);
    }
    //find a pair of files named *.onnx and *.onnx.json
    for (auto file : std::filesystem::directory_iterator(voice_dir)) {
        if (file.path().extension() == ".onnx"
            && std::filesystem::exists(
                file.path().string() + std::string(".json"))) {
            //normal function exit
            return file.path();
        }
    }

    //error case of no valid voices
    std::cerr << "the voice directory (" << voice_dir << ") contains no voices";
    std::exit(1);
}

int main() {
    std::filesystem::path voice_onnx_path = get_any_voice();
    std::filesystem::path voice_json_path
        = voice_onnx_path.string() + std::string(".json");
    piper_synthesizer *synth = piper_create(voice_onnx_path.c_str(),
                                            voice_json_path.c_str(),
                                            BUILD_ENV_ESPEAK_NG_DATA);

    // aplay -r 22050 -c 1 -f FLOAT_LE -t raw output.raw
    std::ofstream audio_stream("output.raw", std::ios::binary);

    piper_synthesize_options options = piper_default_synthesize_options(synth);
    // Change options here:
    // options.length_scale = 2;
    // options.speaker_id = 5;

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

// vim: ts=4 sw=4 expandtab
