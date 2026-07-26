#include <gtest/gtest.h>
#include <memory>
#include <sstream>

#include "piper.h"
#include "utils/piper_test_assets.h"
#include "utils/wavfile.hpp"

class WavFileTest : public ::testing::Test {
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

std::unique_ptr<PiperTestAssets> WavFileTest::assets = nullptr;
piper_synthesizer *WavFileTest::synth = nullptr;

TEST_F(WavFileTest, TextToWavFile) {
  std::stringstream audio_stream;
  piper_synthesize_options options = piper_default_synthesize_options(synth);
  options.speaker_id = 0;

  textToWavFile(synth, &options, "This is a test.", audio_stream);

  std::string audio_data = audio_stream.str();
  // Should have a 44-byte header plus some audio data
  ASSERT_GT(audio_data.length(), 44);
  ASSERT_EQ(audio_data.substr(0, 4), "RIFF");
}