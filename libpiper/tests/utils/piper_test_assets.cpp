#include "piper_test_assets.h"
#include <gtest/gtest.h>

PiperTestAssets::PiperTestAssets(std::filesystem::path modelDir) : modelDir(std::move(modelDir)) {
}

std::filesystem::path PiperTestAssets::modelPath() const {
    return modelDir / "model.onnx";
}

std::filesystem::path PiperTestAssets::configPath() const {
    return modelDir / "model.onnx.json";
}

std::filesystem::path PiperTestAssets::espeakDataPath() {
    return std::filesystem::path(ESPEAK_DATA_PATH);
}

std::unique_ptr<PiperTestAssets> PiperTestAssets::enModel() {
    return std::make_unique<PiperTestAssets>(EN_TEST_MODEL_DIR);
}
