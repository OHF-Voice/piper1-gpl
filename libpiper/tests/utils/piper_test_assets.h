#pragma once

#include <filesystem>
#include <memory>

class PiperTestAssets {
public:
  /** @brief Constructor that takes the directory of the test model. */
  explicit PiperTestAssets(std::filesystem::path modelDir);

  /** @brief Destructor. */
  ~PiperTestAssets() = default;

  [[nodiscard]] auto modelPath() const -> std::filesystem::path;

  [[nodiscard]] auto configPath() const -> std::filesystem::path;

  static auto espeakDataPath() -> std::filesystem::path;

  /**
   * @brief Static factory method to get the default English model assets.
   */
  static auto enModel() -> std::unique_ptr<PiperTestAssets>;

  /**
   * @brief Static factory method to get the model with Text phonemes assets.
   */
  static auto textModel() -> std::unique_ptr<PiperTestAssets>;

private:
  std::filesystem::path modelDir;
};
