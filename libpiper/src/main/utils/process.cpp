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
    
    std::string line;
    while (getline(std::cin, line)) {
        if (line.empty()) {
            continue;
        }

        piper_synthesize_options local_options = *options;
        auto outputType = runConfig.outputType;
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
                local_options.speaker_id =
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
            {
                // Output audio to automatically-named WAV file in a directory
                std::ofstream audioFile(outputPath.string(), std::ios::binary);
                textToWavFile(piper, &local_options, line.c_str(), audioFile);
            } // audioFile is closed
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
            {
                // Output audio to WAV file
                std::ofstream audioFile(outputPath.string(), std::ios::binary);
                textToWavFile(piper, &local_options, line.c_str(), audioFile);
            } // audioFile is closed
            std::cout << outputPath.string() << std::endl;
        } else if (outputType == piper::OUTPUT_STDOUT) {
            // Output WAV to stdout
            textToWavFile(piper, &local_options, line.c_str(), std::cout);
        }
    } // for each line
}