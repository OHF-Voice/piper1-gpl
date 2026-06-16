#include <piper.h>

#include <filesystem>
#include <fstream>
#include <iostream>

#include "CommandLine.h"
#include "helpers.h"
#include "json.hpp"

int main(int argc, char *argv[]) {
    bool print_help = false;
    bool play_file = false;
    float scale_factor = 1.0f;
    int speaker_id = 0;
    std::string filename("en_US-hfc_female-medium");
    auto wav_file =
        std::filesystem::current_path().append("output.wav").string();

    std::string espeak_ng_data;
    std::string text(R"(
The quick brown fox jumps over the lazy dog.
A shimmering lake reflected the golden hues of the setting sun,
while a gentle breeze rustled the leaves of the ancient oak trees.
Somewhere in the distance, a bird chirped a melody that seemed to echo through the quiet valley.
)");

    // Configure command line options.
    CommandLine args("Piper speech library.");
    args.addArgument({"-m", "--model"}, &filename, "The model base filename.");
    args.addArgument(
        {"-s", "--speaker"}, &speaker_id, "Speaker id which defaults to zero.");
    args.addArgument({"-p", "--play"}, &play_file, "Play the file.");
    args.addArgument({"-o", "--output"},
                     &wav_file,
                     "Output to file (defaults: output.wav).");
    args.addArgument({"-e", "--espeak-ng"},
                     &espeak_ng_data,
                     "Location of the espeak-ng-data directory.");
    args.addArgument({"-t", "--text"}, &text, "Text to synthesize.");
    args.addArgument({"-f", "--factor"},
                     &scale_factor,
                     "Scale factor (0.5 - 2.0) for changing the length of the "
                     "output audio.");
    args.addArgument({"-h", "--help"}, &print_help, "Print this help.");
    // Do the actual parsing.
    try {
        args.parse(argc, argv);
    } catch (std::runtime_error const &e) {
        std::cout << e.what() << std::endl;
        args.printHelp();
        return 1;
    }
    if (print_help) {
        args.printHelp();
        return 0;
    }
    // Set the development location for the directory.
    if (!espeak_ng_data.length())
        espeak_ng_data = getExecutablePath()
                             .parent_path()
                             .parent_path()
                             .parent_path()
                             .append("src")
                             .append("piper")
                             .append("espeak-ng-data")
                             .string();

    // Try finding the 'models' directory one directory up.
    if (!std::filesystem::exists(std::filesystem::path(espeak_ng_data))) {
        std::cerr << "Subdirectory 'espeak-ng-data' not found at:"
                  << espeak_ng_data << std::endl;
        return 1;
    }

    std::clog << "Directory 'espeak-ng-data' at: " << espeak_ng_data
              << std::endl;

    // Set the base of the model directory, which is the executable directory.
    auto model_dir = getExecutablePath().parent_path();
    // Try finding the 'models' directory there.
    if (!std::filesystem::exists(
            std::filesystem::path(model_dir).append("models")))
        model_dir = model_dir.parent_path();
    // Try finding the 'models' directory one directory up.
    if (!std::filesystem::exists(
            std::filesystem::path(model_dir).append("models"))) {
        std::cerr << "Subdirectory 'models' not found !" << std::endl;
        return 1;
    }
    // Check if the directory contains the
    auto model_data = model_dir.append("models").append(filename + ".onnx");
    if (!std::filesystem::exists(model_data)) {
        std::cerr << "Model file not found at: " << model_data << std::endl;
        return 1;
    }

    std::clog << "Filepath (model_data): " << model_data << std::endl;

    auto *synth = piper_create(model_data.string().data(),
                               (model_data.string() + ".json").data(),
                               espeak_ng_data.data());

    piper_synthesize_options options = piper_default_synthesize_options(synth);
    // Set the default or selected speaker.
    options.speaker_id = speaker_id;
    options.length_scale *= 1.0f / scale_factor;
    // Start synthesizing.
    int result = piper_synthesize_start(synth, text.c_str(), &options);
    if (result == PIPER_ERR_GENERIC) {
        std::cerr << "Synthesis start failed!" << std::endl;
        return 1;
    }

    std::ofstream audio_stream(wav_file, std::ios::binary);

    piper_audio_chunk chunk;

    int sample_total = 0;
    while ((result = piper_synthesize_next(synth, &chunk)) != PIPER_DONE) {
        if (result == PIPER_ERR_GENERIC) {
            std::cerr << "Synthesis next failed!" << std::endl;
            return 1;
        }
        // Write header the first time.
        if (!sample_total) {
            writeWavHeader(chunk.sample_rate, chunk.num_samples, audio_stream);
            // When the first chunk is also the last.
            if (chunk.is_last) {
                audio_stream.write(
                    reinterpret_cast<const char *>(chunk.samples),
                    chunk.num_samples * sizeof(float));
                continue;
            }
        }
        // Write the samples to the stream.
        audio_stream.write(reinterpret_cast<const char *>(chunk.samples),
                           chunk.num_samples * sizeof(float));
        // update the total amount.
        sample_total += chunk.num_samples;
        // When this is the last chunk of data, Update the header with the
        // correct number of samples.
        if (chunk.is_last)
            writeWavHeader(chunk.sample_rate,
                           sample_total,
                           audio_stream.seekp(0, std::ios::beg));
    }
    // Close the file to make it fully available.
    audio_stream.close();
    // Free synthesizer resources.
    piper_free(synth);
    // Play the wav-file.
    if (play_file) {
#ifdef _WIN32
        auto file = std::filesystem::path(wav_file);
        if (isWine()) {
            std::cout << "Wine detected?" << std::endl;
            std::string cmd("start /d \"");
            cmd += std::filesystem::current_path().string() + "\"";
            cmd += " /unix /usr/bin/xdg-open";
            cmd += " \"./" + file.filename().string() + "\"";
            std::cout << "Command: " << cmd << std::endl;
            return std::system(cmd.data());
        }
        std::string cmd("start");
        cmd += " " + file.filename().string();
        return std::system(cmd.data());
#else
        auto cmd = std::string("xdg-open ").append(wav_file);
        std::cout << "Command: " << cmd << std::endl;
        return std::system(cmd.data());
#endif
    }
    //
    return 0;
}