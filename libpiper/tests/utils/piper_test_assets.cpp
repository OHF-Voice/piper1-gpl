#include "piper_test_assets.h"

#include <gtest/gtest.h>

PiperTestAssets::PiperTestAssets(std::filesystem::path modelDir)
    : modelDir(std::move(modelDir))
{
}

auto PiperTestAssets::modelPath() const -> std::filesystem::path
{
  return modelDir / "model.onnx";
}

auto PiperTestAssets::configPath() const -> std::filesystem::path
{
  return modelDir / "model.onnx.json";
}

auto PiperTestAssets::espeakDataPath() -> std::filesystem::path
{
  return {ESPEAK_DATA_PATH};
}

auto PiperTestAssets::enModel() -> std::unique_ptr<PiperTestAssets>
{
  return std::make_unique<PiperTestAssets>(EN_TEST_MODEL_DIR);
}

auto PiperTestAssets::textModel() -> std::unique_ptr<PiperTestAssets>
{
  return std::make_unique<PiperTestAssets>(TEXT_TEST_MODEL_DIR);
}

auto PiperTestAssets::zhModel() -> std::unique_ptr<PiperTestAssets>
{
  return std::make_unique<PiperTestAssets>(ZH_TEST_MODEL_DIR);
}

auto PiperTestAssets::g2pwDataDir() -> std::filesystem::path
{
#ifdef G2PW_TEST_DATA_DIR
  return {G2PW_TEST_DATA_DIR};
#else
  return {};
#endif
}
