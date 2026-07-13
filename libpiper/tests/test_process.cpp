#include <gtest/gtest.h>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <memory>
#include <sstream>

#include "utils/process.hpp"
#include "utils/piper_test_assets.h"
#include "piper.h"

namespace {
// RAII class to redirect stdin for tests
class StdinRedirect {
public:
  StdinRedirect(const std::string &input) {
    // Create a temporary file with the input
    std::filesystem::path tempPath =
        std::filesystem::temp_directory_path() / "stdin.txt";
    std::ofstream tempFile(tempPath);
    tempFile << input;
    tempFile.close();

    // Redirect stdin
    old_stdin = freopen(tempPath.c_str(), "r", stdin);
  }

  ~StdinRedirect() {
    // Restore stdin and clean up
    if (old_stdin) {
      freopen(old_stdin_path, "r", stdin);
      fclose(old_stdin);
    }
    std::filesystem::remove(std::filesystem::temp_directory_path() /
                            "stdin.txt");
  }

private:
  FILE *old_stdin = nullptr;
  // This is platform-specific, but works for this test case
  const char *old_stdin_path = "/dev/tty";
};
} // namespace

class ProcessTest : public ::testing::Test {
protected:
  static std::unique_ptr<PiperTestAssets> assets;
  static piper_synthesizer *synth;

  static void SetUpTestSuite() {
    assets = PiperTestAssets::enModel();
    synth = piper_create(assets->modelPath().string().c_str(),
                         assets->configPath().string().c_str(),
                         PiperTestAssets::espeakDataPath().string().c_str());
    ASSERT_NE(synth, nullptr);
  }

  static void TearDownTestSuite() {
    piper_free(synth);
    assets.reset();
  }
};

std::unique_ptr<PiperTestAssets> ProcessTest::assets = nullptr;
piper_synthesizer *ProcessTest::synth = nullptr;

TEST_F(ProcessTest, ProcessInputStreamText) {
  piper::RunConfig runConfig;
  runConfig.outputType = piper::OUTPUT_STDOUT;
  runConfig.speakerId = 0;

  StdinRedirect redirect("This is a test.");

  // Redirect cout to check output
  std::stringstream cout_buffer;
  std::streambuf *old_cout = std::cout.rdbuf(cout_buffer.rdbuf());

  processInputStream(runConfig, synth, nullptr);

  std::cout.rdbuf(old_cout); // Restore cout

  std::string audio_data = cout_buffer.str();
  // Should have a 44-byte header plus some audio data
  ASSERT_GT(audio_data.length(), 44);
  ASSERT_EQ(audio_data.substr(0, 4), "RIFF");
}

TEST_F(ProcessTest, ProcessInputStreamJson) {
  piper::RunConfig runConfig;
  runConfig.outputType = piper::OUTPUT_STDOUT;
  runConfig.jsonInput = true;
  runConfig.speakerId = 0;

  StdinRedirect redirect("{\"text\": \"This is a JSON test.\"}");

  std::stringstream cout_buffer;
  std::streambuf *old_cout = std::cout.rdbuf(cout_buffer.rdbuf());

  processInputStream(runConfig, synth, nullptr);

  std::cout.rdbuf(old_cout);

  std::string audio_data = cout_buffer.str();
  ASSERT_GT(audio_data.length(), 44);
  ASSERT_EQ(audio_data.substr(0, 4), "RIFF");
}