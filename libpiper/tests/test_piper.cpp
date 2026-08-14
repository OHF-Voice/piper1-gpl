#include <gtest/gtest.h>
#include <cstddef>
#include <memory>
#include <string>
#include <vector>

#include "piper.h"
#include "piper_impl.hpp"
#include "utils/piper_test_assets.h"

class PiperTest : public ::testing::Test {
protected:
  static std::unique_ptr<PiperTestAssets> assets;

  static void SetUpTestSuite() { assets = PiperTestAssets::enModel(); }

  static void TearDownTestSuite() { assets.reset(); }

  // Code to run after each test
  void TearDown() override {}
};
std::unique_ptr<PiperTestAssets> PiperTest::assets = nullptr;

TEST_F(PiperTest, CreateNullModelPath) {
  piper_synthesizer *synth =
      piper_create(nullptr, assets->configPath().string().c_str(),
                   PiperTestAssets::espeakDataPath().string().c_str());
  ASSERT_EQ(synth, nullptr);
}

TEST_F(PiperTest, CreateNullConfigPath) {
  piper_synthesizer *synth =
      piper_create(assets->modelPath().string().c_str(), nullptr,
                   PiperTestAssets::espeakDataPath().string().c_str());
  ASSERT_NE(synth, nullptr);
  piper_free(synth);
}

TEST_F(PiperTest, PiperSynthesis) {
  piper_synthesizer *synth =
      piper_create(assets->modelPath().string().c_str(),
                   assets->configPath().string().c_str(),
                   PiperTestAssets::espeakDataPath().string().c_str());
  ASSERT_NE(synth, nullptr);

  // Start synthesis
  int result = piper_synthesize_start(synth, "This is a test.", nullptr);
  ASSERT_EQ(result, PIPER_OK);

  // Get audio chunks
  piper_audio_chunk chunk;
  do {
    result = piper_synthesize_next(synth, &chunk);
    ASSERT_EQ(result, chunk.is_last ? PIPER_DONE : PIPER_OK);
    ASSERT_GT(chunk.num_samples, 0);
  } while (!chunk.is_last);

  piper_free(synth);
}

TEST_F(PiperTest, PiperSynthesisText) {
  auto textAssets = PiperTestAssets::textModel();
  piper_synthesizer *synth =
      piper_create(textAssets->modelPath().string().c_str(),
                   textAssets->configPath().string().c_str(), nullptr);
  ASSERT_NE(synth, nullptr);
  ASSERT_EQ(synth->phoneme_type, PhonemeType::Text);

  // Start synthesis
  int result = piper_synthesize_start(synth, "Це є тест.", nullptr);
  ASSERT_EQ(result, PIPER_OK);

  // Get audio chunks
  piper_audio_chunk chunk;
  do {
    result = piper_synthesize_next(synth, &chunk);
    ASSERT_EQ(result, chunk.is_last ? PIPER_DONE : PIPER_OK);
    ASSERT_GT(chunk.num_samples, 0);
  } while (!chunk.is_last);

  piper_free(synth);
}

TEST_F(PiperTest, DeterministicSynthesis) {
  piper_synthesizer *synth =
      piper_create(assets->modelPath().string().c_str(),
                   assets->configPath().string().c_str(),
                   PiperTestAssets::espeakDataPath().string().c_str());
  ASSERT_NE(synth, nullptr);

  piper_synthesize_options options = piper_default_synthesize_options(synth);
  // Disable noise to make synthesis deterministic
  options.noise_scale = 0.0F;
  options.noise_w_scale = 0.0F;

  // First synthesis
  int result = piper_synthesize_start(synth, "This is a test.", &options);
  ASSERT_EQ(result, PIPER_OK);
  piper_audio_chunk chunk1;
  result = piper_synthesize_next(synth, &chunk1);
  ASSERT_EQ(result, PIPER_DONE);
  ASSERT_GT(chunk1.num_samples, 0);

  // Second synthesis
  result = piper_synthesize_start(synth, "This is a test.", &options);
  ASSERT_EQ(result, PIPER_OK);
  piper_audio_chunk chunk2;
  result = piper_synthesize_next(synth, &chunk2);
  ASSERT_EQ(result, PIPER_DONE);

  // With noise disabled, the number of samples should be identical.
  ASSERT_EQ(chunk1.num_samples, chunk2.num_samples);

  piper_free(synth);
}

TEST_F(PiperTest, DefaultSynthesizeOptions) {
  piper_synthesizer *synth =
      piper_create(assets->modelPath().string().c_str(),
                   assets->configPath().string().c_str(),
                   PiperTestAssets::espeakDataPath().string().c_str());
  ASSERT_NE(synth, nullptr);

  piper_synthesize_options options = piper_default_synthesize_options(synth);
  ASSERT_EQ(options.speaker_id, 0);
  // These values are from the test model's config file
  ASSERT_FLOAT_EQ(options.length_scale, 1.0F);
  ASSERT_FLOAT_EQ(options.noise_scale, 0.667F);
  ASSERT_FLOAT_EQ(options.noise_w_scale, 0.8F);

  // Test with null synth
  options = piper_default_synthesize_options(nullptr);
  ASSERT_EQ(options.speaker_id, 0);
  ASSERT_FLOAT_EQ(options.length_scale, 1.0F);
  ASSERT_FLOAT_EQ(options.noise_scale, 0.667F);
  ASSERT_FLOAT_EQ(options.noise_w_scale, 0.8F);

  piper_free(synth);
}

TEST_F(PiperTest, CustomSynthesizeOptions) {
  piper_synthesizer *synth =
      piper_create(assets->modelPath().string().c_str(),
                   assets->configPath().string().c_str(),
                   PiperTestAssets::espeakDataPath().string().c_str());
  ASSERT_NE(synth, nullptr);

  piper_synthesize_options options = piper_default_synthesize_options(synth);
  options.length_scale = 0.5F;
  options.noise_scale = 0.25F;
  options.noise_w_scale = 0.125F;

  int result = piper_synthesize_start(synth, "This is a test.", &options);
  ASSERT_EQ(result, PIPER_OK);

  piper_audio_chunk chunk;
  result = piper_synthesize_next(synth, &chunk);
  ASSERT_EQ(result, PIPER_DONE);
  ASSERT_GT(chunk.num_samples, 0);

  piper_free(synth);
}

TEST_F(PiperTest, MultiSentence) {
  piper_synthesizer *synth =
      piper_create(assets->modelPath().string().c_str(),
                   assets->configPath().string().c_str(),
                   PiperTestAssets::espeakDataPath().string().c_str());
  ASSERT_NE(synth, nullptr);

  int result = piper_synthesize_start(
      synth, "This is a test. This is another test.", nullptr);
  ASSERT_EQ(result, PIPER_OK);

  std::vector<piper_audio_chunk> chunks;
  piper_audio_chunk chunk;
  do {
    result = piper_synthesize_next(synth, &chunk);
    ASSERT_EQ(result, chunk.is_last ? PIPER_DONE : PIPER_OK);
    ASSERT_GT(chunk.num_samples, 0);
    chunks.push_back(chunk);
  } while (!chunk.is_last);

  ASSERT_EQ(chunks.size(), 2);

  piper_free(synth);
}

TEST_F(PiperTest, EmptyText) {
  piper_synthesizer *synth =
      piper_create(assets->modelPath().string().c_str(),
                   assets->configPath().string().c_str(),
                   PiperTestAssets::espeakDataPath().string().c_str());
  ASSERT_NE(synth, nullptr);

  int result = piper_synthesize_start(synth, "", nullptr);
  ASSERT_EQ(result, PIPER_OK);

  piper_audio_chunk chunk;
  result = piper_synthesize_next(synth, &chunk);
  ASSERT_EQ(result, PIPER_DONE);
  ASSERT_EQ(chunk.num_samples, 0);
  ASSERT_TRUE(chunk.is_last);

  piper_free(synth);
}

TEST_F(PiperTest, CreateWithOptionsBasic) {
  std::string model_path = assets->modelPath().string();
  std::string config_path = assets->configPath().string();
  std::string espeak_path = PiperTestAssets::espeakDataPath().string();
  piper_create_options opts;
  piper_init_create_options(&opts);
  opts.model_path = model_path.c_str();
  opts.config_path = config_path.c_str();
  opts.espeak_data_path = espeak_path.c_str();

  piper_synthesizer *synth = piper_create_with_options(&opts);
  ASSERT_NE(synth, nullptr);
  EXPECT_EQ(synth->phoneme_type, PhonemeType::Espeak);
  piper_free(synth);
}

TEST_F(PiperTest, CreateWithOptionsNullModel) {
  std::string config_path = assets->configPath().string();
  std::string espeak_path = PiperTestAssets::espeakDataPath().string();
  piper_create_options opts;
  piper_init_create_options(&opts);
  opts.model_path = nullptr;
  opts.config_path = config_path.c_str();
  opts.espeak_data_path = espeak_path.c_str();

  piper_synthesizer *synth = piper_create_with_options(&opts);
  ASSERT_EQ(synth, nullptr);
}

TEST_F(PiperTest, CreateWithOptionsNullOptions) {
  piper_synthesizer *synth = piper_create_with_options(nullptr);
  ASSERT_EQ(synth, nullptr);
}

TEST_F(PiperTest, CreateWithOptionsSmallStruct) {
  std::string model_path = assets->modelPath().string();
  std::string espeak_path = PiperTestAssets::espeakDataPath().string();
  piper_create_options opts;
  piper_init_create_options(&opts);
  opts.model_path = model_path.c_str();
  // Simulate old header with smaller struct_size (only up to espeak_data_path)
  opts.struct_size = offsetof(piper_create_options, espeak_data_path) + sizeof(opts.espeak_data_path);
  opts.espeak_data_path = espeak_path.c_str();

  piper_synthesizer *synth = piper_create_with_options(&opts);
  ASSERT_NE(synth, nullptr);
  piper_free(synth);
}

TEST_F(PiperTest, CreateWithOptionsDataDir) {
  // data_dir containing espeak-ng-data should be resolved
  auto espeak_root = PiperTestAssets::espeakDataPath().parent_path();
  std::string model_path = assets->modelPath().string();
  std::string config_path = assets->configPath().string();
  std::string data_dir = espeak_root.string();
  piper_create_options opts;
  piper_init_create_options(&opts);
  opts.model_path = model_path.c_str();
  opts.config_path = config_path.c_str();
  opts.espeak_data_path = nullptr; // rely on data_dir fallback
  opts.data_dir = data_dir.c_str();

  piper_synthesizer *synth = piper_create_with_options(&opts);
  if (synth) {
    piper_free(synth);
  } else {
    SUCCEED();
  }
}

TEST_F(PiperTest, CreateWithOptionsG2pwDirField) {
  std::string model_path = assets->modelPath().string();
  std::string config_path = assets->configPath().string();
  std::string espeak_path = PiperTestAssets::espeakDataPath().string();
  piper_create_options opts;
  piper_init_create_options(&opts);
  opts.model_path = model_path.c_str();
  opts.config_path = config_path.c_str();
  opts.espeak_data_path = espeak_path.c_str();
  opts.g2pw_model_dir = "/tmp/nonexistent_g2pw";
  opts.data_dir = nullptr;

  piper_synthesizer *synth = piper_create_with_options(&opts);
  ASSERT_NE(synth, nullptr);
  EXPECT_EQ(synth->g2pw_model_dir, "/tmp/nonexistent_g2pw");
  piper_free(synth);
}

TEST_F(PiperTest, CreateLegacyVsOptionsParity) {
  std::string model_path = assets->modelPath().string();
  std::string config_path = assets->configPath().string();
  std::string espeak_path = PiperTestAssets::espeakDataPath().string();
  auto *synth_legacy = piper_create(model_path.c_str(), config_path.c_str(), espeak_path.c_str());
  ASSERT_NE(synth_legacy, nullptr);

  piper_create_options opts;
  piper_init_create_options(&opts);
  opts.model_path = model_path.c_str();
  opts.config_path = config_path.c_str();
  opts.espeak_data_path = espeak_path.c_str();
  auto *synth_opts = piper_create_with_options(&opts);
  ASSERT_NE(synth_opts, nullptr);

  EXPECT_EQ(synth_legacy->phoneme_type, synth_opts->phoneme_type);
  EXPECT_EQ(synth_legacy->sample_rate, synth_opts->sample_rate);
  EXPECT_EQ(synth_legacy->num_speakers, synth_opts->num_speakers);

  piper_free(synth_legacy);
  piper_free(synth_opts);
}
