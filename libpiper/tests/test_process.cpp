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
  StdinRedirect(const std::string &input) : old_cin(std::cin.rdbuf()) {
    input_buffer << input;
    std::cin.rdbuf(input_buffer.rdbuf());
  }

  ~StdinRedirect() {
    // Restore stdin and clean up
    std::cin.rdbuf(old_cin);
  }

private:
  std::streambuf *old_cin;
  std::stringstream input_buffer;
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

  piper_synthesize_options options = piper_default_synthesize_options(synth);
  options.speaker_id = 0;

  StdinRedirect redirect("This is a test.");

  // Redirect cout to check output
  std::stringstream cout_buffer;
  std::streambuf *old_cout = std::cout.rdbuf(cout_buffer.rdbuf());

  processInputStream(runConfig, synth, &options);

  std::cout.rdbuf(old_cout); // Restore cout

  std::string audio_data = cout_buffer.str();
  // Should have a 44-byte header plus some audio data
  ASSERT_GT(audio_data.length(), 44);
  ASSERT_EQ(audio_data.substr(0, 4), "RIFF");
}

TEST_F(ProcessTest, ProcessInputStreamFileOutput) {
  piper::RunConfig runConfig;
  auto outputPath = std::filesystem::temp_directory_path() / "test.wav";
  runConfig.outputPath = outputPath;
  runConfig.outputType = piper::OUTPUT_FILE;

  piper_synthesize_options options = piper_default_synthesize_options(synth);
  options.speaker_id = 0;

  StdinRedirect redirect("This is a test for file output.");

  // Redirect cout to capture the output path
  std::stringstream cout_buffer;
  std::streambuf* old_cout = std::cout.rdbuf(cout_buffer.rdbuf());

  processInputStream(runConfig, synth, &options);

  std::cout.rdbuf(old_cout); // Restore cout

  // Verify the output file was created and has content
  ASSERT_TRUE(std::filesystem::exists(outputPath));
  {
    std::ifstream audio_file(outputPath, std::ios::binary | std::ios::ate);
    ASSERT_TRUE(audio_file.is_open());
    std::streamsize size = audio_file.tellg();
    ASSERT_GT(size, 44); // Should have a 44-byte header plus some audio data
  }
  // Clean up the created file
  std::filesystem::remove(outputPath);
}

TEST_F(ProcessTest, ProcessInputStreamDirectoryOutput) {
  piper::RunConfig runConfig;
  auto outputDir = std::filesystem::temp_directory_path() / "piper_test_output";
  std::filesystem::create_directory(outputDir);
  runConfig.outputPath = outputDir;
  runConfig.outputType = piper::OUTPUT_DIRECTORY;

  piper_synthesize_options options = piper_default_synthesize_options(synth);
  options.speaker_id = 0;

  StdinRedirect redirect("This is a test for directory output.");

  std::stringstream cout_buffer;
  std::streambuf* old_cout = std::cout.rdbuf(cout_buffer.rdbuf());

  processInputStream(runConfig, synth, &options);

  std::cout.rdbuf(old_cout);

  std::string created_path = cout_buffer.str();
  created_path.erase(created_path.find_last_not_of(" \n\r\t")+1);
  ASSERT_TRUE(std::filesystem::exists(created_path));
  ASSERT_GT(std::filesystem::file_size(created_path), 44);
  std::filesystem::remove_all(outputDir);
}

TEST_F(ProcessTest, ProcessInputStreamJson) {
  piper::RunConfig runConfig;
  runConfig.outputType = piper::OUTPUT_STDOUT;
  runConfig.jsonInput = true;

  piper_synthesize_options options = piper_default_synthesize_options(synth);
  options.speaker_id = 0;

  StdinRedirect redirect("{\"text\": \"This is a JSON test.\"}");

  std::stringstream cout_buffer;
  std::streambuf *old_cout = std::cout.rdbuf(cout_buffer.rdbuf());

  processInputStream(runConfig, synth, &options);

  std::cout.rdbuf(old_cout);

  std::string audio_data = cout_buffer.str();
  ASSERT_GT(audio_data.length(), 44);
  ASSERT_EQ(audio_data.substr(0, 4), "RIFF");
}