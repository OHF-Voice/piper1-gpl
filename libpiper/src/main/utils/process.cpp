#include "process.hpp"
#include "wavfile.hpp"
#include "json.hpp"

#include <chrono>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>

using json = nlohmann::json;

void processInputStream(piper::RunConfig &runConfig, piper_synthesizer *piper, piper_synthesize_options *options) {
    std::unique_ptr<piper_synthesize_options> default_options;
    if (!options) {
        default_options = std::make_unique<piper_synthesize_options>(
            piper_default_synthesize_options(piper));
        options = default_options.get();
    }

    // Speaker ID
    if (runConfig.speakerId) {
        options->speaker_id = runConfig.speakerId.value();
    }

    // Scales
    if (runConfig.noiseScale) {
        options->noise_scale = runConfig.noiseScale.value();
    }

    if (runConfig.lengthScale) {
        options->length_scale = runConfig.lengthScale.value();
    }

    if (runConfig.noiseW) {
        options->noise_w_scale = runConfig.noiseW.value();
    }

    std::string line;
    while (getline(std::cin, line)) {

        auto outputType = runConfig.outputType;
        auto speakerId = options->speaker_id;
        std::optional<std::filesystem::path> maybeOutputPath = runConfig.outputPath;

        if (runConfig.jsonInput) {
            // Each line is a JSON object
            json lineRoot = json::parse(line);

            // Text is required
            line = lineRoot["text"].get<std::string>();

            if (lineRoot.contains("output_file")) {
                // Override output WAV file path
                outputType = piper::OUTPUT_FILE;
                maybeOutputPath =
                    std::filesystem::path(lineRoot["output_file"].get<std::string>());
            }

            if (lineRoot.contains("speaker_id")) {
                // Override speaker id
                options->speaker_id =
                    lineRoot["speaker_id"].get<int>();
            }
        }

        // Timestamp is used for path to output WAV file
        const auto now = std::chrono::system_clock::now();
        const auto timestamp =
            std::chrono::duration_cast<std::chrono::nanoseconds>(now.time_since_epoch())
            .count();
        if (outputType == piper::OUTPUT_DIRECTORY) {
            // Generate path using timestamp
            std::stringstream outputName;
            outputName << timestamp << ".wav";
            std::filesystem::path outputPath = runConfig.outputPath.value();
            outputPath.append(outputName.str());

            // Output audio to automatically-named WAV file in a directory
            std::ofstream audioFile(outputPath.string(), std::ios::binary);
            textToWavFile(runConfig, piper, options, line.c_str(), audioFile);
            std::cout << outputPath.string() << std::endl;
        } else if (outputType == piper::OUTPUT_FILE) {
            if (!maybeOutputPath || maybeOutputPath->empty()) {
                throw std::runtime_error("No output path provided");
            }
            std::filesystem::path outputPath = maybeOutputPath.value();

            if (!runConfig.jsonInput) {
                // Read all of standard input before synthesizing.
                // Otherwise, we would overwrite the output file for each line.
                std::stringstream text;
                text << line;
                while (getline(std::cin, line)) {
                    text << " " << line;
                }

                line = text.str();
            }

            // Output audio to WAV file
            std::ofstream audioFile(outputPath.string(), std::ios::binary);
            textToWavFile(runConfig, piper, options, line.c_str(), audioFile);
            std::cout << outputPath.string() << std::endl;
        } else if (outputType == piper::OUTPUT_STDOUT) {
            // Output WAV to stdout
            textToWavFile(runConfig, piper, options, line.c_str(), std::cout);
        }

        // Restore config (--json-input)
        options->speaker_id = speakerId;

    } // for each line
}