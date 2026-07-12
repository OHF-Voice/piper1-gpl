#include <gtest/gtest.h>
#include <string>
#include <memory>

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
