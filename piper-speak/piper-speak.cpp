#include <piper.h>
#include <filesystem>
#include <iostream>
#include <fstream>
#include <string>
#include "audio.h"

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

//call afer piper_synthesize_start to play the synthesized data
void play_piper_chunks(piper_synthesizer* synth,
    const piper_synthesize_options& options) {
    piper_audio_chunk chunk;
    while (piper_synthesize_next(synth, &chunk) != PIPER_DONE) {
        //set to seem like a good volume for piper's output
        constexpr float volume = 1.5;
        play_audio(chunk.samples, chunk.num_samples, volume);
    }
}

void read_string(piper_synthesizer* synth,
    const piper_synthesize_options& options, 
    const std::string& toRead) {
    piper_synthesize_start(synth, toRead.c_str(), &options);
    play_piper_chunks(synth, options);
}

void read_file(piper_synthesizer* synth,
    const piper_synthesize_options& options, const std::filesystem::path& filename) {
    std::ifstream file(filename);
    if (!file.is_open()) {
        std::cerr << "failed to read: " << filename << "\n";
        exit(1);
    }
    //this is suboptimal because perhaps the entire file doesn't fit in memory
    std::string entire_file = std::string(
        std::istreambuf_iterator<char>(file),
        std::istreambuf_iterator<char>()
    ); 
    
    read_string(synth, options, entire_file);
}

void read_stdin(piper_synthesizer* synth,
    const piper_synthesize_options& options) {
    //we are loading input line by line here.
    //This is suboptimal as it means that piper doesn't see
    //the entire sentence, leading to weird innotation. 
    //likewise very long lines could cause memory hogging issues.
    std::string line;
    while (std::getline(std::cin, line)) {
        piper_synthesize_start(synth, line.c_str(), &options);
        play_piper_chunks(synth, options);
    }
}

constexpr std::string_view help_string = 
"USAGE: \n"
"piper-speak --help OR piper-speak -h        prints this help\n"
"piper-speak -f <file-to-read>               reads a file\n"
"piper-speak '<words to speak...>'           reads the commandline argument\n"
"piper-speak OR piper-speak --stdin'         reads stdin line by line\n";

int main(int argc, char** argv) {
    std::filesystem::path voice_onnx_path = get_any_voice();
    std::filesystem::path voice_json_path
        = voice_onnx_path.string() + std::string(".json");
    piper_synthesizer *synth = piper_create(voice_onnx_path.c_str(),
                                            voice_json_path.c_str(),
                                            BUILD_ENV_ESPEAK_NG_DATA);
    //initialize the audio to play
    init_audio();

    piper_synthesize_options options = piper_default_synthesize_options(synth);
    // Change options here:
    // options.length_scale = 2;
    // options.speaker_id = 5;

    if (argc > 1 && 
        (std::string(argv[1]) == "--help"
            || std::string(argv[1]) == "-h"
        )) {
        std::cerr << help_string;
    } else if (argc == 1
        || (argc == 2 && std::string(argv[1]) == "--stdin")
       ){
         read_stdin(synth, options);
    } else if (argc == 3 && std::string(argv[1]) == "-f") {
        read_file(synth, options, argv[2]);
    } else if (argc == 2) {
        read_string(synth, options, argv[1]);
    } else {
        std::cerr << "invalid commandline arguments\n";
        std::cerr << help_string;
    }
    
    wait_for_audio_to_finish();
    piper_free(synth);
    cleanup_audio();
    return 0;
}

// vim: ts=4 sw=4 expandtab
