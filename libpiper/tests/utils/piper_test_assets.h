#pragma once

#include <filesystem>
#include <memory>
#include <string>

class PiperTestAssets {
public:
  /** @brief Constructor that takes the directory of the test model. */
  explicit PiperTestAssets(std::filesystem::path modelDir);

  /** @brief Destructor. */
  ~PiperTestAssets() = default;

  std::filesystem::path modelPath() const;

  std::filesystem::path configPath() const;

  static std::filesystem::path espeakDataPath();

  /**
   * @brief Static factory method to get the default English model assets.
   */
  static std::unique_ptr<PiperTestAssets> enModel();

  /**
   * @brief Static factory method to get the model with Text phonemes assets.
   */
  static std::unique_ptr<PiperTestAssets> textModel();

private:
  std::filesystem::path modelDir;
};
