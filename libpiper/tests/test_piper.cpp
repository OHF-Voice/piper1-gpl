#include <gtest/gtest.h>
#include <string>
#include <memory>
#include <vector>

#include "piper.h"
#include "utils/piper_test_assets.h"

class PiperTest : public ::testing::Test {
protected:
    static std::unique_ptr<PiperTestAssets> assets;

    static void SetUpTestSuite() {
        assets = PiperTestAssets::enModel();
    }

    static void TearDownTestSuite() {
        assets.reset();
    }

    // Code to run after each test
    void TearDown() override {}
};
std::unique_ptr<PiperTestAssets> PiperTest::assets = nullptr;

TEST_F(PiperTest, CreateNullModelPath) {
    piper_synthesizer *synth = piper_create(
        nullptr,
        assets->configPath().string().c_str(),
        PiperTestAssets::espeakDataPath().string().c_str());
    ASSERT_EQ(synth, nullptr);
}

TEST_F(PiperTest, CreateNullConfigPath) {
    piper_synthesizer *synth = piper_create(
        assets->modelPath().string().c_str(),
        nullptr,
        PiperTestAssets::espeakDataPath().string().c_str());
    ASSERT_NE(synth, nullptr);
    piper_free(synth);
}

TEST_F(PiperTest, PiperSynthesis) {
    piper_synthesizer *synth = piper_create(
        assets->modelPath().string().c_str(),
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

TEST_F(PiperTest, DeterministicSynthesis) {
    piper_synthesizer *synth = piper_create(
        assets->modelPath().string().c_str(),
        assets->configPath().string().c_str(),
        PiperTestAssets::espeakDataPath().string().c_str());
    ASSERT_NE(synth, nullptr);

    piper_synthesize_options options = piper_default_synthesize_options(synth);
    // Disable noise to make synthesis deterministic
    options.noise_scale = 0.0f;
    options.noise_w_scale = 0.0f;

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
    piper_synthesizer *synth = piper_create(
        assets->modelPath().string().c_str(),
        assets->configPath().string().c_str(),
        PiperTestAssets::espeakDataPath().string().c_str());
    ASSERT_NE(synth, nullptr);

    piper_synthesize_options options = piper_default_synthesize_options(synth);
    ASSERT_EQ(options.speaker_id, 0);
    // These values are from the test model's config file
    ASSERT_FLOAT_EQ(options.length_scale, 1.0f);
    ASSERT_FLOAT_EQ(options.noise_scale, 0.667f);
    ASSERT_FLOAT_EQ(options.noise_w_scale, 0.8f);

    // Test with null synth
    options = piper_default_synthesize_options(nullptr);
    ASSERT_EQ(options.speaker_id, 0);
    ASSERT_FLOAT_EQ(options.length_scale, 1.0f);
    ASSERT_FLOAT_EQ(options.noise_scale, 0.667f);
    ASSERT_FLOAT_EQ(options.noise_w_scale, 0.8f);

    piper_free(synth);
}

TEST_F(PiperTest, CustomSynthesizeOptions) {
    piper_synthesizer *synth = piper_create(
        assets->modelPath().string().c_str(),
        assets->configPath().string().c_str(),
        PiperTestAssets::espeakDataPath().string().c_str());
    ASSERT_NE(synth, nullptr);

    piper_synthesize_options options = piper_default_synthesize_options(synth);
    options.length_scale = 0.5f;
    options.noise_scale = 0.25f;
    options.noise_w_scale = 0.125f;

    int result = piper_synthesize_start(synth, "This is a test.", &options);
    ASSERT_EQ(result, PIPER_OK);

    piper_audio_chunk chunk;
    result = piper_synthesize_next(synth, &chunk);
    ASSERT_EQ(result, PIPER_DONE);
    ASSERT_GT(chunk.num_samples, 0);

    piper_free(synth);
}

TEST_F(PiperTest, MultiSentence) {
    piper_synthesizer *synth = piper_create(
        assets->modelPath().string().c_str(),
        assets->configPath().string().c_str(),
        PiperTestAssets::espeakDataPath().string().c_str());
    ASSERT_NE(synth, nullptr);

    int result = piper_synthesize_start(synth, "This is a test. This is another test.", nullptr);
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
    piper_synthesizer *synth = piper_create(
        assets->modelPath().string().c_str(),
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
