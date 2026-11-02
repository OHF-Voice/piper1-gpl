#include "main_utils.hpp"

#include <filesystem>
#include <fstream>
#include <iostream>
#include <optional>
#include <stdexcept>
#include <string>

#include "piper.h"

namespace piper {

void printUsage(char *argv[]) { // NOLINT(modernize-avoid-c-arrays)
  std::cerr << '\n';
  std::cerr << "usage: " << argv[0] << " [options]" << '\n';
  std::cerr << '\n';
  std::cerr << "options:" << '\n';
  std::cerr << "   -h        --help              show this message and exit"
            << '\n';
  std::cerr << "   -m  FILE  --model       FILE  path to onnx model file"
            << '\n';
  std::cerr << "   -c  FILE  --config      FILE  path to model config file "
               "(default: model path + .json)"
            << '\n';
  std::cerr << "   -f  FILE  --output_file FILE  path to output WAV file ('-' "
               "for stdout)"
            << '\n';
  std::cerr << "   -d  DIR   --output_dir  DIR   path to output directory "
               "(default: cwd)"
            << '\n';
  std::cerr << "   -s  NUM   --speaker     NUM   id of speaker (default: 0)"
            << '\n';
  std::cerr
      << "   --noise_scale           NUM   generator noise (default: 0.667)"
      << '\n';
  std::cerr << "   --length_scale          NUM   phoneme length (default: 1.0)"
            << '\n';
  std::cerr
      << "   --noise_w               NUM   phoneme width noise (default: 0.8)"
      << '\n';
  std::cerr
      << "   --espeak_data           DIR   path to espeak-ng data directory"
      << '\n';
  std::cerr << "   --data_dir            DIR   base data dir (looks for "
               "espeak-ng-data and g2pw subdirs)"
            << '\n';
  std::cerr << "   --g2pw_dir            DIR   path to Chinese dict directory "
               "(MONOPHONIC_CHARS.txt, char_bopomofo_dict.json etc)"
            << '\n';
  std::cerr << "   --json-input                  stdin input is lines of JSON "
               "instead of plain text"
            << '\n';
  std::cerr << '\n';
}

// NOLINTNEXTLINE(modernize-avoid-c-arrays)
void ensureArg(int argc, char *argv[], int argi) {
  if ((argi + 1) >= argc) {
    throw ArgError(std::string("Missing argument for ") + argv[argi]);
  }
}

// Parse command-line arguments
// NOLINTNEXTLINE(readability-function-cognitive-complexity,modernize-avoid-c-arrays)
void parseArgsLogic(int argc, char *argv[], RunConfig &runConfig) {
  std::optional<std::filesystem::path> modelConfigPath;

  for (int i = 1; i < argc; i++) {
    std::string arg = argv[i];

    if (arg == "-m" || arg == "--model") {
      ensureArg(argc, argv, i);
      runConfig.modelPath = std::filesystem::path(argv[++i]);
    } else if (arg == "-c" || arg == "--config") {
      ensureArg(argc, argv, i);
      modelConfigPath = std::filesystem::path(argv[++i]);
    } else if (arg == "-f" || arg == "--output_file" ||
               arg == "--output-file") {
      ensureArg(argc, argv, i);
      std::string filePath = argv[++i];
      if (filePath == "-") {
        runConfig.outputType = OUTPUT_STDOUT;
        runConfig.outputPath = std::nullopt;
      } else {
        runConfig.outputType = OUTPUT_FILE;
        runConfig.outputPath = std::filesystem::path(filePath);
      }
    } else if (arg == "-d" || arg == "--output_dir" || arg == "--output-dir") {
      ensureArg(argc, argv, i);
      runConfig.outputType = OUTPUT_DIRECTORY;
      runConfig.outputPath = std::filesystem::path(argv[++i]);
    } else if (arg == "-s" || arg == "--speaker") {
      ensureArg(argc, argv, i);
      runConfig.speakerId = std::stol(argv[++i]);
    } else if (arg == "--noise_scale" || arg == "--noise-scale") {
      ensureArg(argc, argv, i);
      runConfig.noiseScale = std::stof(argv[++i]);
    } else if (arg == "--length_scale" || arg == "--length-scale") {
      ensureArg(argc, argv, i);
      runConfig.lengthScale = std::stof(argv[++i]);
    } else if (arg == "--noise_w" || arg == "--noise-w") {
      ensureArg(argc, argv, i);
      runConfig.noiseW = std::stof(argv[++i]);
    } else if (arg == "--espeak_data" || arg == "--espeak-data") {
      ensureArg(argc, argv, i);
      runConfig.eSpeakDataPath = std::filesystem::path(argv[++i]);
    } else if (arg == "--data_dir" || arg == "--data-dir") {
      ensureArg(argc, argv, i);
      runConfig.dataDir = std::filesystem::path(argv[++i]);
    } else if (arg == "--g2pw_dir" || arg == "--g2pw-dir" ||
               arg == "--g2pw_model_dir" || arg == "--g2pw-model-dir") {
      ensureArg(argc, argv, i);
      runConfig.g2pwModelDir = std::filesystem::path(argv[++i]);
    } else if (arg == "--json_input" || arg == "--json-input") {
      runConfig.jsonInput = true;
    } else if (arg == "--version") {
      std::cout << piper_version() << '\n';
      exit(0);
    } else if (arg == "-h" || arg == "--help") {
      printUsage(argv);
      exit(0);
    }
  }

  // Verify model file exists
  std::ifstream modelFile(runConfig.modelPath.c_str(), std::ios::binary);
  if (!modelFile.good()) {
    throw std::runtime_error("Model file doesn't exist");
  }

  if (!modelConfigPath) {
    runConfig.modelConfigPath =
        std::filesystem::path(runConfig.modelPath.string() + ".json");
  } else {
    runConfig.modelConfigPath = modelConfigPath.value();
  }

  // Verify model config exists
  std::ifstream modelConfigFile(runConfig.modelConfigPath.c_str());
  if (!modelConfigFile.good()) {
    throw std::runtime_error("Model config doesn't exist");
  }
}

// NOLINTNEXTLINE(modernize-avoid-c-arrays)
void parseArgs(int argc, char *argv[], RunConfig &runConfig) {
  try {
    parseArgsLogic(argc, argv, runConfig);
  } catch (const ArgError &e) {
    std::cerr << e.what() << '\n';
    printUsage(argv);
    exit(1);
  } catch (const std::exception &e) {
    std::cerr << e.what() << '\n';
    exit(1);
  }
}

} // namespace piper