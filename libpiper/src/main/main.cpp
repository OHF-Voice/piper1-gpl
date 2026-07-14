#include <chrono>
#include <condition_variable>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iostream>
#include <map>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

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

#include "utils/process.hpp"
#include "utils/main_utils.hpp"

#include "json.hpp"
#include "piper.h"
#include "piper_impl.hpp"

using namespace std;

// ----------------------------------------------------------------------------

int main(int argc, char *argv[]) {
  piper::RunConfig runConfig;
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

  // Speaker ID
  if (runConfig.speakerId) {
    options.speaker_id = runConfig.speakerId.value();
  }

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

  if (runConfig.outputType == piper::OUTPUT_DIRECTORY) {
    runConfig.outputPath = filesystem::absolute(runConfig.outputPath.value());
  }

  processInputStream(runConfig, piper, &options);

  piper_free(piper);

  return EXIT_SUCCESS;
}