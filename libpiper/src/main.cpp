#include <chrono>
#include <condition_variable>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iostream>
#include <map>
#include <mutex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>
#include <print>

#ifdef _MSC_VER
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#endif

#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif

#ifdef __APPLE__
#include <mach-o/dyld.h>
#endif

#include "wavfile.hpp"

#include "json.hpp"
#include "piper.h"
#include "piper_impl.hpp"

using namespace std;
using json = nlohmann::json;

enum OutputType { OUTPUT_FILE, OUTPUT_DIRECTORY, OUTPUT_STDOUT };

struct RunConfig {
  // Path to .onnx voice file
  filesystem::path modelPath;

  // Path to JSON voice config file
  filesystem::path modelConfigPath;

  // Type of output to produce.
  // Default is to write a WAV file in the current directory.
  OutputType outputType = OUTPUT_DIRECTORY;

  // Path for output
  optional<filesystem::path> outputPath = filesystem::path(".");

  // Numerical id of the default speaker (multi-speaker voices)
  optional<int> speakerId;

  // Amount of noise to add during audio generation
  optional<float> noiseScale;

  // Speed of speaking (1 = normal, < 1 is faster, > 1 is slower)
  optional<float> lengthScale;

  // Variation in phoneme lengths
  optional<float> noiseW;

  // Path to espeak-ng data directory (default is next to piper executable)
  optional<filesystem::path> eSpeakDataPath;

  // stdin input is lines of JSON instead of text with format:
  // {
  //   "text": str,               (required)
  //   "speaker_id": int,         (optional)
  //   "output_file": str,        (optional)
  // }
  bool jsonInput = false;
};

void parseArgs(int argc, char *argv[], RunConfig &runConfig);
void rawOutputProc(vector<int16_t> &sharedAudioBuffer, mutex &mutAudio,
                   condition_variable &cvAudio, bool &audioReady,
                   bool &audioFinished);
void writeWavStreamHeader(std::ostream& stream, int sampleRate);

// ----------------------------------------------------------------------------

int main(int argc, char *argv[]) {
  RunConfig runConfig;
  parseArgs(argc, argv, runConfig);

#ifdef _WIN32
  // Required on Windows to show IPA symbols
  SetConsoleOutputCP(CP_UTF8);
#endif
  piper_synthesizer *piper;

  // Get the path to the piper executable so we can locate espeak-ng-data, etc.
  // next to it.
#ifdef _MSC_VER
  auto exePath = []() {
    wchar_t moduleFileName[MAX_PATH] = {0};
    GetModuleFileNameW(nullptr, moduleFileName, std::size(moduleFileName));
    return filesystem::path(moduleFileName);
  }();
#else
#ifdef __APPLE__
  auto exePath = []() {
    char moduleFileName[PATH_MAX] = {0};
    uint32_t moduleFileNameSize = std::size(moduleFileName);
    _NSGetExecutablePath(moduleFileName, &moduleFileNameSize);
    return filesystem::path(moduleFileName);
  }();
#else
  auto exePath = filesystem::canonical("/proc/self/exe");
#endif
#endif

    if (runConfig.eSpeakDataPath) {
      // User provided path
      runConfig.eSpeakDataPath = runConfig.eSpeakDataPath.value().string();
    } else {
      // Assume next to piper executable
      runConfig.eSpeakDataPath =
          std::filesystem::absolute(
              exePath.parent_path().append("espeak-ng-data"))
              .string();
    }
  auto startTime = chrono::steady_clock::now();
  piper = piper_create(runConfig.modelPath.string().c_str(),
                       runConfig.modelConfigPath.string().c_str(),
                       runConfig.eSpeakDataPath->string().c_str()
                      );
  auto endTime = chrono::steady_clock::now();

  piper_synthesize_options options;
  options.speaker_id = 0;
  options.length_scale = DEFAULT_LENGTH_SCALE;
  options.noise_scale = DEFAULT_NOISE_SCALE;
  options.noise_w_scale = DEFAULT_NOISE_W_SCALE;

  // Scales
  if (runConfig.noiseScale) {
    options.noise_scale = runConfig.noiseScale.value();
  }

  if (runConfig.lengthScale) {
    options.length_scale = runConfig.lengthScale.value();
  }

  if (runConfig.noiseW) {
    options.noise_w_scale = runConfig.noiseW.value();
  }

  if (runConfig.outputType == OUTPUT_DIRECTORY) {
    runConfig.outputPath = filesystem::absolute(runConfig.outputPath.value());
  }

  string line;
  while (getline(cin, line)) {

    auto outputType = runConfig.outputType;
    auto speakerId = options.speaker_id;
    std::optional<filesystem::path> maybeOutputPath = runConfig.outputPath;

    if (runConfig.jsonInput) {
      // Each line is a JSON object
      json lineRoot = json::parse(line);

      // Text is required
      line = lineRoot["text"].get<std::string>();

      if (lineRoot.contains("output_file")) {
        // Override output WAV file path
        outputType = OUTPUT_FILE;
        maybeOutputPath =
            filesystem::path(lineRoot["output_file"].get<std::string>());
      }

      if (lineRoot.contains("speaker_id")) {
        // Override speaker id
        options.speaker_id =
            lineRoot["speaker_id"].get<int>();
      }
    }

    // Timestamp is used for path to output WAV file
    const auto now = chrono::system_clock::now();
    const auto timestamp =
        chrono::duration_cast<chrono::nanoseconds>(now.time_since_epoch())
            .count();
    if (outputType == OUTPUT_DIRECTORY) {
      // Generate path using timestamp
      stringstream outputName;
      outputName << timestamp << ".wav";
      filesystem::path outputPath = runConfig.outputPath.value();
      outputPath.append(outputName.str());

      // Output audio to automatically-named WAV file in a directory
      ofstream audioFile(outputPath.string(), ios::binary);
      textToWavFile(piper, options, line.c_str(), audioFile);
      cout << outputPath.string() << endl;
    } else if (outputType == OUTPUT_FILE) {
      if (!maybeOutputPath || maybeOutputPath->empty()) {
        throw runtime_error("No output path provided");
      }
      filesystem::path outputPath = maybeOutputPath.value();

      if (!runConfig.jsonInput) {
        // Read all of standard input before synthesizing.
        // Otherwise, we would overwrite the output file for each line.
        stringstream text;
        text << line;
        while (getline(cin, line)) {
          text << " " << line;
        }

        line = text.str();
      }

      // Output audio to WAV file
      ofstream audioFile(outputPath.string(), ios::binary);
      textToWavFile(piper, options, line.c_str(), audioFile);
      cout << outputPath.string() << endl;
    } else if (outputType == OUTPUT_STDOUT) {
      // Output WAV to stdout
      textToWavFile(piper, options, line.c_str(), cout);
    }

    // Restore config (--json-input)
    options.speaker_id = speakerId;

  } // for each line

  piper_free(piper);

  return EXIT_SUCCESS;
}

// ----------------------------------------------------------------------------

void rawOutputProc(vector<int16_t> &sharedAudioBuffer, mutex &mutAudio,
                   condition_variable &cvAudio, bool &audioReady,
                   bool &audioFinished) {
  vector<int16_t> internalAudioBuffer;
  while (true) {
    {
      unique_lock lockAudio{mutAudio};
      cvAudio.wait(lockAudio, [&audioReady] { return audioReady; });

      if (sharedAudioBuffer.empty() && audioFinished) {
        break;
      }

      copy(sharedAudioBuffer.begin(), sharedAudioBuffer.end(),
           back_inserter(internalAudioBuffer));

      sharedAudioBuffer.clear();

      if (!audioFinished) {
        audioReady = false;
      }
    }

    cout.write((const char *)internalAudioBuffer.data(),
               sizeof(int16_t) * internalAudioBuffer.size());
    cout.flush();
    internalAudioBuffer.clear();
  }

} // rawOutputProc

// ----------------------------------------------------------------------------

void printUsage(char *argv[]) {
  cerr << endl;
  cerr << "usage: " << argv[0] << " [options]" << endl;
  cerr << endl;
  cerr << "options:" << endl;
  cerr << "   -h        --help              show this message and exit" << endl;
  cerr << "   -m  FILE  --model       FILE  path to onnx model file" << endl;
  cerr << "   -c  FILE  --config      FILE  path to model config file "
          "(default: model path + .json)"
       << endl;
  cerr << "   -f  FILE  --output_file FILE  path to output WAV file ('-' for "
          "stdout)"
       << endl;
  cerr << "   -d  DIR   --output_dir  DIR   path to output directory (default: "
          "cwd)"
       << endl;
  cerr << "   -s  NUM   --speaker     NUM   id of speaker (default: 0)" << endl;
  cerr << "   --noise_scale           NUM   generator noise (default: 0.667)"
       << endl;
  cerr << "   --length_scale          NUM   phoneme length (default: 1.0)"
       << endl;
  cerr << "   --noise_w               NUM   phoneme width noise (default: 0.8)"
       << endl;
  cerr << "   --espeak_data           DIR   path to espeak-ng data directory"
       << endl;
  cerr << "   --tashkeel_model        FILE  path to libtashkeel onnx model "
          "(arabic)"
       << endl;
  cerr << "   --json-input                  stdin input is lines of JSON "
          "instead of plain text"
       << endl;
  cerr << endl;
}

void ensureArg(int argc, char *argv[], int argi) {
  if ((argi + 1) >= argc) {
    printUsage(argv);
    exit(0);
  }
}

// Parse command-line arguments
void parseArgs(int argc, char *argv[], RunConfig &runConfig) {
  optional<filesystem::path> modelConfigPath;

  for (int i = 1; i < argc; i++) {
    std::string arg = argv[i];

    if (arg == "-m" || arg == "--model") {
      ensureArg(argc, argv, i);
      runConfig.modelPath = filesystem::path(argv[++i]);
    } else if (arg == "-c" || arg == "--config") {
      ensureArg(argc, argv, i);
      modelConfigPath = filesystem::path(argv[++i]);
    } else if (arg == "-f" || arg == "--output_file" ||
               arg == "--output-file") {
      ensureArg(argc, argv, i);
      std::string filePath = argv[++i];
      if (filePath == "-") {
        runConfig.outputType = OUTPUT_STDOUT;
        runConfig.outputPath = nullopt;
      } else {
        runConfig.outputType = OUTPUT_FILE;
        runConfig.outputPath = filesystem::path(filePath);
      }
    } else if (arg == "-d" || arg == "--output_dir" || arg == "output-dir") {
      ensureArg(argc, argv, i);
      runConfig.outputType = OUTPUT_DIRECTORY;
      runConfig.outputPath = filesystem::path(argv[++i]);
    } else if (arg == "-s" || arg == "--speaker") {
      ensureArg(argc, argv, i);
      runConfig.speakerId = stol(argv[++i]);
    } else if (arg == "--noise_scale" || arg == "--noise-scale") {
      ensureArg(argc, argv, i);
      runConfig.noiseScale = stof(argv[++i]);
    } else if (arg == "--length_scale" || arg == "--length-scale") {
      ensureArg(argc, argv, i);
      runConfig.lengthScale = stof(argv[++i]);
    } else if (arg == "--noise_w" || arg == "--noise-w") {
      ensureArg(argc, argv, i);
      runConfig.noiseW = stof(argv[++i]);
    } else if (arg == "--espeak_data" || arg == "--espeak-data") {
      ensureArg(argc, argv, i);
      runConfig.eSpeakDataPath = filesystem::path(argv[++i]);
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
  ifstream modelFile(runConfig.modelPath.c_str(), ios::binary);
  if (!modelFile.good()) {
    throw runtime_error("Model file doesn't exist");
  }

  if (!modelConfigPath) {
    runConfig.modelConfigPath =
        filesystem::path(runConfig.modelPath.string() + ".json");
  } else {
    runConfig.modelConfigPath = modelConfigPath.value();
  }

  // Verify model config exists
  ifstream modelConfigFile(runConfig.modelConfigPath.c_str());
  if (!modelConfigFile.good()) {
    throw runtime_error("Model config doesn't exist");
  }
}