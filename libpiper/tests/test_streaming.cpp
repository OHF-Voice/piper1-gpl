#include <algorithm>
#include <cmath>
#include <filesystem>
#include <gtest/gtest.h>
#include <memory>
#include <string>
#include <vector>

#include "piper.h"
#include "utils/piper_test_assets.h"

namespace {

struct SynthesisResult {
  std::vector<float> samples;
  std::size_t num_chunks = 0;
  std::size_t num_chunks_with_phonemes = 0;
};

auto synthesize(piper_synthesizer *synth, const char *text) -> SynthesisResult {
  piper_synthesize_options options = piper_default_synthesize_options(synth);
  // Disable noise so the split and the full model give the same audio
  options.noise_scale = 0.0F;
  options.noise_w_scale = 0.0F;

  SynthesisResult result;
  EXPECT_EQ(piper_synthesize_start(synth, text, &options), PIPER_OK);

  piper_audio_chunk chunk;
  int status = PIPER_OK;
  do {
    status = piper_synthesize_next(synth, &chunk);
    EXPECT_EQ(status, chunk.is_last ? PIPER_DONE : PIPER_OK);
    EXPECT_GT(chunk.num_samples, 0);
    result.samples.insert(result.samples.end(), chunk.samples,
                          chunk.samples + chunk.num_samples);
    result.num_chunks++;
    if (chunk.num_phonemes > 0) {
      result.num_chunks_with_phonemes++;
    }
  } while (status == PIPER_OK);

  return result;
}

auto create(const PiperTestAssets &assets) -> piper_synthesizer * {
  return piper_create(assets.modelPath().string().c_str(),
                      assets.configPath().string().c_str(),
                      PiperTestAssets::espeakDataPath().string().c_str());
}

} // namespace

class StreamingTest : public ::testing::Test {
protected:
  void SetUp() override {
    full_assets = PiperTestAssets::enModel();
    split_assets = PiperTestAssets::enStreamingModel();

    auto decoder_path =
        split_assets->modelPath().parent_path() / "model.decoder.onnx";
    if (!std::filesystem::exists(decoder_path)) {
      GTEST_SKIP() << "Split test voice not found (needs Python with onnx)";
    }
  }

  std::unique_ptr<PiperTestAssets> full_assets;
  std::unique_ptr<PiperTestAssets> split_assets;
};

TEST_F(StreamingTest, MatchesFullModel) {
  const char *text = "This is a test. This is another, slightly longer test "
                     "sentence that needs several chunks.";

  piper_synthesizer *full_synth = create(*full_assets);
  ASSERT_NE(full_synth, nullptr);
  auto expected = synthesize(full_synth, text);
  piper_free(full_synth);

  piper_synthesizer *split_synth = create(*split_assets);
  ASSERT_NE(split_synth, nullptr);
  auto streamed = synthesize(split_synth, text);
  piper_free(split_synth);

  // One chunk per sentence without streaming
  ASSERT_EQ(expected.num_chunks, 2);
  ASSERT_GT(streamed.num_chunks, expected.num_chunks);

  // Phonemes come once per sentence, with its first chunk
  ASSERT_EQ(streamed.num_chunks_with_phonemes, 2);

  ASSERT_EQ(streamed.samples.size(), expected.samples.size());
  float max_difference = 0;
  for (std::size_t i = 0; i < expected.samples.size(); i++) {
    max_difference = std::max(
        max_difference, std::abs(expected.samples[i] - streamed.samples[i]));
  }
  EXPECT_LT(max_difference, 1e-3F);
}

TEST_F(StreamingTest, RestartDiscardsPreviousSentence) {
  piper_synthesizer *synth = create(*split_assets);
  ASSERT_NE(synth, nullptr);

  auto expected = synthesize(synth, "This is a test.");

  // Abandon a synthesis after its first chunk
  ASSERT_EQ(
      piper_synthesize_start(
          synth, "A different sentence that is left unfinished.", nullptr),
      PIPER_OK);
  piper_audio_chunk chunk;
  ASSERT_EQ(piper_synthesize_next(synth, &chunk), PIPER_OK);

  auto restarted = synthesize(synth, "This is a test.");
  piper_free(synth);

  ASSERT_EQ(restarted.samples.size(), expected.samples.size());
  ASSERT_EQ(restarted.num_chunks_with_phonemes, 1);
}
