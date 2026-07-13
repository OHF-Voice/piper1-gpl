#include <gtest/gtest.h>

#include <filesystem>
#include <fstream>
#include <string>
#include <vector>

#include "utils/main_utils.hpp"

class MainUtilsTest : public ::testing::Test {
protected:
  void SetUp() override {
    // Create dummy files for validation to pass
    std::ofstream modelFile("model.onnx");
    std::ofstream("model.onnx.json").close();
    std::ofstream("config.json").close();
    std::ofstream("out.wav").close();
  }

  void TearDown() override {
    std::filesystem::remove("model.onnx");
    std::filesystem::remove("model.onnx.json");
    std::filesystem::remove("config.json");
    std::filesystem::remove("out.wav");
  }
};

TEST_F(MainUtilsTest, ParseArgsBasic) {
  piper::RunConfig runConfig;

  const char *argv[] = {"test_program", "--model", "model.onnx",
                        "--output_file", "output.wav"};
  int argc = sizeof(argv) / sizeof(argv[0]);

  parseArgsLogic(argc, const_cast<char **>(argv), runConfig);

  EXPECT_EQ(runConfig.modelPath, "model.onnx");
  EXPECT_EQ(runConfig.outputPath.value(), "output.wav");
}

TEST_F(MainUtilsTest, ParseArgsNoOutputFile) {
  piper::RunConfig runConfig;

  const char *argv[] = {"test_program", "--model", "model.onnx"};
  int argc = sizeof(argv) / sizeof(argv[0]);

  parseArgsLogic(argc, const_cast<char **>(argv), runConfig);

  EXPECT_EQ(runConfig.modelPath, "model.onnx");
  // Defaults to output directory "."
  EXPECT_EQ(runConfig.outputType, piper::OUTPUT_DIRECTORY);
  EXPECT_EQ(runConfig.outputPath.value(), ".");
}

TEST_F(MainUtilsTest, ParseArgsWithSpeaker) {
  piper::RunConfig runConfig;

  const char *argv[] = {"test_program", "--model", "model.onnx", "--speaker", "1"};
  int argc = sizeof(argv) / sizeof(argv[0]);

  parseArgsLogic(argc, const_cast<char **>(argv), runConfig);

  EXPECT_EQ(runConfig.modelPath, "model.onnx");
  ASSERT_TRUE(runConfig.speakerId.has_value());
  EXPECT_EQ(runConfig.speakerId.value(), 1);
}

TEST_F(MainUtilsTest, ParseArgsAllParams) {
  piper::RunConfig runConfig;

  const char *argv[] = {"test_program",   "--model",        "model.onnx",
                        "--config",       "config.json",    "--output_file",
                        "out.wav",        "--speaker",      "5",
                        "--noise_scale",  "0.5",            "--length_scale",
                        "1.2",            "--noise_w",      "0.8"};
  int argc = sizeof(argv) / sizeof(argv[0]);

  parseArgsLogic(argc, const_cast<char **>(argv), runConfig);

  EXPECT_EQ(runConfig.modelPath, "model.onnx");
  EXPECT_EQ(runConfig.modelConfigPath, "config.json");
  EXPECT_EQ(runConfig.outputPath.value(), "out.wav");
  ASSERT_TRUE(runConfig.speakerId.has_value());
  EXPECT_EQ(runConfig.speakerId.value(), 5);
  ASSERT_TRUE(runConfig.noiseScale.has_value());
  EXPECT_FLOAT_EQ(runConfig.noiseScale.value(), 0.5f);
  ASSERT_TRUE(runConfig.lengthScale.has_value());
  EXPECT_FLOAT_EQ(runConfig.lengthScale.value(), 1.2f);
  ASSERT_TRUE(runConfig.noiseW.has_value());
  EXPECT_FLOAT_EQ(runConfig.noiseW.value(), 0.8f);
}

TEST_F(MainUtilsTest, ParseArgsMissingModel) {
  piper::RunConfig runConfig;

  // Don't create dummy model file
  std::filesystem::remove("model.onnx");

  const char *argv[] = {"test_program", "--model", "model.onnx"};
  int argc = sizeof(argv) / sizeof(argv[0]);

  // This should throw an exception
  EXPECT_THROW(
      try {
        parseArgsLogic(argc, const_cast<char **>(argv), runConfig);
      } catch (const std::runtime_error &e) {
        EXPECT_STREQ(e.what(), "Model file doesn't exist");
        throw;
      },
      std::runtime_error);
}