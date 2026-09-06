#include <chrono>
#include <filesystem>
#include <iostream>
#include <map>
#include <string>
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

#include "piper.h"
#include "piper_impl.hpp"
#include "utils/main_utils.hpp"
#include "utils/process.hpp"

using namespace std;

// ----------------------------------------------------------------------------

auto main(int argc, char* argv[]) -> int
{
  try
  {
    piper::RunConfig runConfig;
    parseArgs(argc, argv, runConfig);

#ifdef _WIN32
    // Required on Windows to show IPA symbols
    SetConsoleOutputCP(CP_UTF8);
#endif
    piper_synthesizer* piper;

    // Get the path to the piper executable so we can locate espeak-ng-data,
    // etc. next to it.
#ifdef _MSC_VER
    auto exePath = []() -> filesystem::path
    {
      wchar_t moduleFileName[MAX_PATH] = {0};
      GetModuleFileNameW(nullptr, moduleFileName, std::size(moduleFileName));
      return filesystem::path(moduleFileName);
    }();
#else
#ifdef __APPLE__
    auto exePath = []() -> filesystem::path
    {
      // NOLINTNEXTLINE(modernize-avoid-c-arrays)
      char moduleFileName[PATH_MAX] = {0};
      uint32_t moduleFileNameSize = std::size(moduleFileName);
      _NSGetExecutablePath(moduleFileName, &moduleFileNameSize);
      return {moduleFileName};
    }();
#else
    auto exePath = filesystem::canonical("/proc/self/exe");
#endif
#endif

    if (runConfig.eSpeakDataPath)
    {
      // User provided path
      // No change needed, it's already a path
    }
    else
    {
      // Assume next to piper executable
      runConfig.eSpeakDataPath = std::filesystem::absolute(exePath.parent_path().append("espeak-ng-data")).string();
    }
    if (!runConfig.eSpeakDataPath.has_value())
    {
      throw std::runtime_error("eSpeak data path not set");
    }

    piper_create_options create_opts;
    piper_init_create_options(&create_opts);
    std::string model_path_str = runConfig.modelPath.string();
    std::string config_path_str = runConfig.modelConfigPath.string();
    std::string espeak_path_str = runConfig.eSpeakDataPath.value().string();
    std::string data_dir_str;
    std::string g2pw_dir_str;
    create_opts.model_path = model_path_str.c_str();
    create_opts.config_path = config_path_str.c_str();
    create_opts.espeak_data_path = espeak_path_str.c_str();
    if (runConfig.dataDir)
    {
      data_dir_str = runConfig.dataDir->string();
      create_opts.data_dir = data_dir_str.c_str();
    }
    if (runConfig.g2pwModelDir)
    {
      g2pw_dir_str = runConfig.g2pwModelDir->string();
      create_opts.g2pw_model_dir = g2pw_dir_str.c_str();
    }
    piper = piper_create_with_options(&create_opts);
    if (!piper)
    {
      // Fallback to legacy for compatibility
      piper = piper_create(model_path_str.c_str(), config_path_str.c_str(), espeak_path_str.c_str());
    }

    piper_synthesize_options options;
    options.speaker_id = 0;
    options.length_scale = DEFAULT_LENGTH_SCALE;
    options.noise_scale = DEFAULT_NOISE_SCALE;
    options.noise_w_scale = DEFAULT_NOISE_W_SCALE;

    // Speaker ID
    if (runConfig.speakerId)
    {
      options.speaker_id = runConfig.speakerId.value();
    }

    // Scales
    if (runConfig.noiseScale)
    {
      options.noise_scale = runConfig.noiseScale.value();
    }

    if (runConfig.lengthScale)
    {
      options.length_scale = runConfig.lengthScale.value();
    }

    if (runConfig.noiseW)
    {
      options.noise_w_scale = runConfig.noiseW.value();
    }

    if (runConfig.outputType == piper::OUTPUT_DIRECTORY)
    {
      // NOLINTNEXTLINE(bugprone-unchecked-optional-access)
      runConfig.outputPath = filesystem::absolute(runConfig.outputPath.value());
    }

    processInputStream(runConfig, piper, &options);

    piper_free(piper);

    return EXIT_SUCCESS;
  }
  catch (const piper::ArgError& e)
  {
    // printUsage is called inside parseArgs
    return EXIT_FAILURE;
  }
  catch (const std::exception& e)
  {
    std::cerr << e.what() << '\n';
    return EXIT_FAILURE;
  }
  catch (...)
  {
    std::cerr << "An unknown error occurred" << '\n';
    return EXIT_FAILURE;
  }
}
