#ifndef PIPER_MAIN_UTILS_HPP
#define PIPER_MAIN_UTILS_HPP

#include <chrono>
#include <filesystem>
#include <optional>
#include <stdexcept>


namespace piper {

enum OutputType { OUTPUT_FILE, OUTPUT_DIRECTORY, OUTPUT_STDOUT };

struct RunConfig {
  // Path to .onnx voice file
  std::filesystem::path modelPath;

  // Path to JSON voice config file
  std::filesystem::path modelConfigPath;

  // Type of output to produce.
  // Default is to write a WAV file in the current directory.
  OutputType outputType = OUTPUT_DIRECTORY;

  // Path for output
  std::optional<std::filesystem::path> outputPath = std::filesystem::path(".");

  // Numerical id of the default speaker (multi-speaker voices)
  std::optional<int> speakerId;
  std::optional<float> noiseScale;
  std::optional<float> lengthScale;
  std::optional<float> noiseW;
  std::optional<std::filesystem::path> eSpeakDataPath;
  bool jsonInput = false;
};

struct ArgError : public std::runtime_error {
  using std::runtime_error::runtime_error;
};

void printUsage(char *argv[]);
void ensureArg(int argc, char *argv[], int argi);
void parseArgsLogic(int argc, char *argv[], RunConfig &runConfig);
void parseArgs(int argc, char *argv[], RunConfig &runConfig);

} // namespace piper
#endif // PIPER_MAIN_UTILS_HPP