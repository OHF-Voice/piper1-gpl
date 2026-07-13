#include "main_utils.hpp"

#include <filesystem>
#include <fstream>
#include <iostream>
#include <optional>
#include <stdexcept>
#include <string>

namespace piper {

void printUsage(char *argv[]) {
  std::cerr << std::endl;
  std::cerr << "usage: " << argv[0] << " [options]" << std::endl;
  std::cerr << std::endl;
  std::cerr << "options:" << std::endl;
  std::cerr << "   -h        --help              show this message and exit"
            << std::endl;
  std::cerr << "   -m  FILE  --model       FILE  path to onnx model file"
            << std::endl;
  std::cerr << "   -c  FILE  --config      FILE  path to model config file "
               "(default: model path + .json)"
            << std::endl;
  std::cerr << "   -f  FILE  --output_file FILE  path to output WAV file ('-' "
               "for stdout)"
            << std::endl;
  std::cerr << "   -d  DIR   --output_dir  DIR   path to output directory "
               "(default: cwd)"
            << std::endl;
  std::cerr << "   -s  NUM   --speaker     NUM   id of speaker (default: 0)"
            << std::endl;
  std::cerr << "   --noise_scale           NUM   generator noise (default: 0.667)"
            << std::endl;
  std::cerr << "   --length_scale          NUM   phoneme length (default: 1.0)"
            << std::endl;
  std::cerr << "   --noise_w               NUM   phoneme width noise (default: 0.8)"
            << std::endl;
  std::cerr << "   --espeak_data           DIR   path to espeak-ng data directory"
            << std::endl;
  std::cerr << "   --json-input                  stdin input is lines of JSON "
               "instead of plain text"
            << std::endl;
  std::cerr << std::endl;
}

void ensureArg(int argc, char *argv[], int argi) {
    if ((argi + 1) >= argc)
    {
        throw ArgError(std::string("Missing argument for ") + argv[argi]);
    }
}

// Parse command-line arguments
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
    } else if (arg == "--json_input" || arg == "--json-input") {
      runConfig.jsonInput = true;
    } else if (arg == "--version") {
      std::cout << "0.0.1" << std::endl;
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

void parseArgs(int argc, char *argv[], RunConfig &runConfig) {
  try {
    parseArgsLogic(argc, argv, runConfig);
  } catch (const ArgError &e) {
    std::cerr << e.what() << std::endl;
    printUsage(argv);
    exit(1);
  } catch (const std::exception &e) {
    std::cerr << e.what() << std::endl;
    exit(1);
  }
}

} // namespace piper