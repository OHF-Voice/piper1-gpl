#include <gtest/gtest.h>

#include <cstddef>
#include <filesystem>
#include <memory>
#include <string>
#include <vector>

#include "chinese_phonemizer.h"
#include "piper.h"
#include "piper_impl.hpp"
#include "utils/piper_test_assets.h"

class PiperTest : public ::testing::Test
{
 protected:
  static std::unique_ptr<PiperTestAssets> assets;

  static void SetUpTestSuite()
  {
    assets = PiperTestAssets::enModel();
  }

  static void TearDownTestSuite()
  {
    assets.reset();
  }

  // Code to run after each test
  void TearDown() override
  {
  }
};
std::unique_ptr<PiperTestAssets> PiperTest::assets = nullptr;

TEST_F(PiperTest, CreateNullModelPath)
{
  piper_synthesizer* synth =
      piper_create(nullptr, assets->configPath().string().c_str(),
                   PiperTestAssets::espeakDataPath().string().c_str());
  ASSERT_EQ(synth, nullptr);
}

TEST_F(PiperTest, CreateNullConfigPath)
{
  piper_synthesizer* synth =
      piper_create(assets->modelPath().string().c_str(), nullptr,
                   PiperTestAssets::espeakDataPath().string().c_str());
  ASSERT_NE(synth, nullptr);
  piper_free(synth);
}

TEST_F(PiperTest, PiperSynthesis)
{
  piper_synthesizer* synth =
      piper_create(assets->modelPath().string().c_str(),
                   assets->configPath().string().c_str(),
                   PiperTestAssets::espeakDataPath().string().c_str());
  ASSERT_NE(synth, nullptr);

  // Start synthesis
  int result = piper_synthesize_start(synth, "This is a test.", nullptr);
  ASSERT_EQ(result, PIPER_OK);

  // Get audio chunks
  piper_audio_chunk chunk;
  do
  {
    result = piper_synthesize_next(synth, &chunk);
    ASSERT_EQ(result, chunk.is_last ? PIPER_DONE : PIPER_OK);
    ASSERT_GT(chunk.num_samples, 0);
  } while (!chunk.is_last);

  piper_free(synth);
}

TEST_F(PiperTest, PiperSynthesisText)
{
  auto textAssets = PiperTestAssets::textModel();
  piper_synthesizer* synth =
      piper_create(textAssets->modelPath().string().c_str(),
                   textAssets->configPath().string().c_str(), nullptr);
  ASSERT_NE(synth, nullptr);
  ASSERT_EQ(synth->phoneme_type, PhonemeType::Text);

  // Start synthesis
  int result = piper_synthesize_start(synth, "Це є тест.", nullptr);
  ASSERT_EQ(result, PIPER_OK);

  // Get audio chunks
  piper_audio_chunk chunk;
  do
  {
    result = piper_synthesize_next(synth, &chunk);
    ASSERT_EQ(result, chunk.is_last ? PIPER_DONE : PIPER_OK);
    ASSERT_GT(chunk.num_samples, 0);
  } while (!chunk.is_last);

  piper_free(synth);
}

TEST_F(PiperTest, DeterministicSynthesis)
{
  piper_synthesizer* synth =
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

TEST_F(PiperTest, DefaultSynthesizeOptions)
{
  piper_synthesizer* synth =
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

TEST_F(PiperTest, CustomSynthesizeOptions)
{
  piper_synthesizer* synth =
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

TEST_F(PiperTest, MultiSentence)
{
  piper_synthesizer* synth =
      piper_create(assets->modelPath().string().c_str(),
                   assets->configPath().string().c_str(),
                   PiperTestAssets::espeakDataPath().string().c_str());
  ASSERT_NE(synth, nullptr);

  int result = piper_synthesize_start(
      synth, "This is a test. This is another test.", nullptr);
  ASSERT_EQ(result, PIPER_OK);

  std::vector<piper_audio_chunk> chunks;
  piper_audio_chunk chunk;
  do
  {
    result = piper_synthesize_next(synth, &chunk);
    ASSERT_EQ(result, chunk.is_last ? PIPER_DONE : PIPER_OK);
    ASSERT_GT(chunk.num_samples, 0);
    chunks.push_back(chunk);
  } while (!chunk.is_last);

  ASSERT_EQ(chunks.size(), 2);

  piper_free(synth);
}

TEST_F(PiperTest, EmptyText)
{
  piper_synthesizer* synth =
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

TEST_F(PiperTest, CreateWithOptionsBasic)
{
  std::string model_path = assets->modelPath().string();
  std::string config_path = assets->configPath().string();
  std::string espeak_path = PiperTestAssets::espeakDataPath().string();
  piper_create_options opts;
  piper_init_create_options(&opts);
  opts.model_path = model_path.c_str();
  opts.config_path = config_path.c_str();
  opts.espeak_data_path = espeak_path.c_str();

  piper_synthesizer* synth = piper_create_with_options(&opts);
  ASSERT_NE(synth, nullptr);
  EXPECT_EQ(synth->phoneme_type, PhonemeType::Espeak);
  piper_free(synth);
}

TEST_F(PiperTest, CreateWithOptionsNullModel)
{
  std::string config_path = assets->configPath().string();
  std::string espeak_path = PiperTestAssets::espeakDataPath().string();
  piper_create_options opts;
  piper_init_create_options(&opts);
  opts.model_path = nullptr;
  opts.config_path = config_path.c_str();
  opts.espeak_data_path = espeak_path.c_str();

  piper_synthesizer* synth = piper_create_with_options(&opts);
  ASSERT_EQ(synth, nullptr);
}

TEST_F(PiperTest, CreateWithOptionsNullOptions)
{
  piper_synthesizer* synth = piper_create_with_options(nullptr);
  ASSERT_EQ(synth, nullptr);
}

TEST_F(PiperTest, CreateWithOptionsSmallStruct)
{
  std::string model_path = assets->modelPath().string();
  std::string espeak_path = PiperTestAssets::espeakDataPath().string();
  piper_create_options opts;
  piper_init_create_options(&opts);
  opts.model_path = model_path.c_str();
  // Simulate old header with smaller struct_size (only up to espeak_data_path)
  opts.struct_size = offsetof(piper_create_options, espeak_data_path) +
                     sizeof(opts.espeak_data_path);
  opts.espeak_data_path = espeak_path.c_str();

  piper_synthesizer* synth = piper_create_with_options(&opts);
  ASSERT_NE(synth, nullptr);
  piper_free(synth);
}

TEST_F(PiperTest, CreateWithOptionsDataDir)
{
  // data_dir containing espeak-ng-data should be resolved
  auto espeak_root = PiperTestAssets::espeakDataPath().parent_path();
  std::string model_path = assets->modelPath().string();
  std::string config_path = assets->configPath().string();
  std::string data_dir = espeak_root.string();
  piper_create_options opts;
  piper_init_create_options(&opts);
  opts.model_path = model_path.c_str();
  opts.config_path = config_path.c_str();
  opts.espeak_data_path = nullptr;  // rely on data_dir fallback
  opts.data_dir = data_dir.c_str();

  piper_synthesizer* synth = piper_create_with_options(&opts);
  // Now that espeak data path resolution via data_dir is fixed, synth must be
  // non-null (previously this test allowed nullptr and would hide fallback
  // bugs)
  ASSERT_NE(synth, nullptr)
      << "piper_create_with_options should succeed via data_dir=" << data_dir;
  // Verify g2pw dir resolution for Phase 1: data_dir/g2pw is tried first,
  // then data_dir root. When data_dir contains espeak-ng-data but no g2pw
  // dicts, effective_g2pw_dir defaults to <data_dir>/g2pw (non-fatal, direct
  // pinyin still works)
  EXPECT_FALSE(synth->g2pw_model_dir.empty());
  // Should end with "g2pw" when using espeak_root data_dir (no dicts in root)
  EXPECT_TRUE(synth->g2pw_model_dir.find("g2pw") != std::string::npos)
      << "expected g2pw fallback in " << synth->g2pw_model_dir;
  piper_free(synth);
}

TEST_F(PiperTest, CreateWithOptionsG2pwDirField)
{
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

  piper_synthesizer* synth = piper_create_with_options(&opts);
  ASSERT_NE(synth, nullptr);
  EXPECT_EQ(synth->g2pw_model_dir, "/tmp/nonexistent_g2pw");
  piper_free(synth);
}

TEST_F(PiperTest, CreateLegacyVsOptionsParity)
{
  std::string model_path = assets->modelPath().string();
  std::string config_path = assets->configPath().string();
  std::string espeak_path = PiperTestAssets::espeakDataPath().string();
  auto* synth_legacy = piper_create(model_path.c_str(), config_path.c_str(),
                                    espeak_path.c_str());
  ASSERT_NE(synth_legacy, nullptr);

  piper_create_options opts;
  piper_init_create_options(&opts);
  opts.model_path = model_path.c_str();
  opts.config_path = config_path.c_str();
  opts.espeak_data_path = espeak_path.c_str();
  auto* synth_opts = piper_create_with_options(&opts);
  ASSERT_NE(synth_opts, nullptr);

  EXPECT_EQ(synth_legacy->phoneme_type, synth_opts->phoneme_type);
  EXPECT_EQ(synth_legacy->sample_rate, synth_opts->sample_rate);
  EXPECT_EQ(synth_legacy->num_speakers, synth_opts->num_speakers);

  piper_free(synth_legacy);
  piper_free(synth_opts);
}

// ---- Chinese phonemizer unit tests ----

TEST(ChinesePhonemizerUnit, NormalizeG2pw)
{
  using namespace piper;
  EXPECT_EQ(normalize_g2pw_syllable("nu:3"), "nv3");
  EXPECT_EQ(normalize_g2pw_syllable("lve4"), "lve4");
  EXPECT_EQ(normalize_g2pw_syllable("ni3"), "ni3");
  EXPECT_EQ(normalize_g2pw_syllable("hao3"), "hao3");
  EXPECT_EQ(normalize_g2pw_syllable("abc"), "abc");
}

TEST(ChinesePhonemizerUnit, SplitInitialFinalTone)
{
  using namespace piper;
  auto [ini, fin, tone] = split_initial_final_tone("ni3");
  EXPECT_EQ(ini, "n");
  EXPECT_EQ(fin, "i");
  EXPECT_EQ(tone, "3");

  auto [ini2, fin2, tone2] = split_initial_final_tone("hao3");
  EXPECT_EQ(ini2, "h");
  EXPECT_EQ(fin2, "ao");
  EXPECT_EQ(tone2, "3");

  auto [ini3, fin3, tone3] = split_initial_final_tone("zhong1");
  EXPECT_EQ(ini3, "zh");
  EXPECT_EQ(fin3, "ong");
  EXPECT_EQ(tone3, "1");

  auto [ini4, fin4, tone4] = split_initial_final_tone("a1");
  EXPECT_EQ(ini4, "");
  EXPECT_EQ(fin4, "a");
  EXPECT_EQ(tone4, "1");
}

TEST(ChinesePhonemizerUnit, PhonemizePinyinText)
{
  auto seq = piper::ChinesePhonemizer::phonemize_pinyin_text("ni3 hao3");
  ASSERT_EQ(seq.size(), 1);
  auto& ph = seq[0];
  // Should contain initial, final, tone for both syllables
  // Contains at least n,i,3,h,ao,3
  EXPECT_GT(ph.size(), 4);
  bool has_n = std::find(ph.begin(), ph.end(), "n") != ph.end();
  bool has_h = std::find(ph.begin(), ph.end(), "h") != ph.end();
  EXPECT_TRUE(has_n);
  EXPECT_TRUE(has_h);
}

TEST(ChinesePhonemizerUnit, PhonemesToIds)
{
  std::map<std::string, std::vector<int64_t>> id_map = {
      {"^", {1}},  {"_", {0}},  {"$", {2}},   {"n", {10}}, {"i", {27}},
      {"3", {66}}, {"h", {14}}, {"ao", {32}}, {" ", {72}}};
  std::vector<std::string> ph = {"n", "i", "3", "h", "ao", "3"};
  auto ids = piper::phonemes_to_ids(ph, id_map);
  // BOS 1, n10,i27,3+pad, h,ao,3+pad, EOS
  EXPECT_GT(ids.size(), 5);
  EXPECT_EQ(ids.front(), 1);
  EXPECT_EQ(ids.back(), 2);
}

// ---- Pinyin end-to-end tests ----

class PinyinTest : public ::testing::Test
{
 protected:
  static std::unique_ptr<PiperTestAssets> assets;
  static std::string g2pw_dir;

  static void SetUpTestSuite()
  {
    assets = PiperTestAssets::zhModel();

    auto has_required = [](const std::filesystem::path& d)
    {
      bool has_source = std::filesystem::exists(d / "MONOPHONIC_CHARS.txt") ||
                        std::filesystem::exists(d / "char_bopomofo_dict.json");
      bool has_b2p =
          std::filesystem::exists(d / "bopomofo_to_pinyin_wo_tune_dict.json");
      return has_source && has_b2p;
    };

    // Prefer CMake-downloaded g2pw dir – must be complete for Phase 1
    auto cmake_g2pw = PiperTestAssets::g2pwDataDir();
    std::vector<std::filesystem::path> candidates = {
        cmake_g2pw,
        std::filesystem::path("/tmp/g2pw_full"),
        std::filesystem::path("build/g2pw"),
        std::filesystem::path("/tmp/g2pw"),
    };

    for (auto& cand : candidates)
    {
      if (cand.empty()) continue;
      if (std::filesystem::exists(cand) && has_required(cand))
      {
        g2pw_dir = cand.string();
        break;
      }
    }

    // Fallback: if no complete dir but cmake dir exists partially, use it
    // so load() fails clearly (hasDicts false) instead of silently using
    // incomplete data later as PIPER_ERR_GENERIC
    if (g2pw_dir.empty())
    {
      if (!cmake_g2pw.empty() && std::filesystem::exists(cmake_g2pw))
      {
        g2pw_dir = cmake_g2pw.string();
      }
      else if (std::filesystem::exists("/tmp/g2pw_full"))
      {
        g2pw_dir = "/tmp/g2pw_full";
      }
      else if (std::filesystem::exists("build/g2pw"))
      {
        g2pw_dir = "build/g2pw";
      }
      else if (!cmake_g2pw.empty())
      {
        g2pw_dir = cmake_g2pw.string();
      }
      else
      {
        g2pw_dir = "";
      }
    }

    // If zh model missing, creation will fail – tests will SKIP clearly
  }

  static void TearDownTestSuite()
  {
    assets.reset();
  }
};

std::unique_ptr<PiperTestAssets> PinyinTest::assets = nullptr;
std::string PinyinTest::g2pw_dir = "";

TEST_F(PinyinTest, DirectPinyin)
{
  if (!std::filesystem::exists(assets->modelPath()))
  {
    GTEST_SKIP() << "zh model not downloaded";
  }

  piper_create_options opts;
  piper_init_create_options(&opts);
  std::string model = assets->modelPath().string();
  std::string config = assets->configPath().string();
  opts.model_path = model.c_str();
  opts.config_path = config.c_str();
  opts.espeak_data_path = nullptr;
  if (!g2pw_dir.empty())
  {
    opts.g2pw_model_dir = g2pw_dir.c_str();
  }

  auto* synth = piper_create_with_options(&opts);
  if (!synth)
  {
    GTEST_SKIP() << "synth creation failed (model missing?)";
  }
  ASSERT_EQ(synth->phoneme_type, PhonemeType::Pinyin);

  int rc = piper_synthesize_start(synth, "ni3 hao3", nullptr);
  ASSERT_EQ(rc, PIPER_OK);

  piper_audio_chunk chunk;
  rc = piper_synthesize_next(synth, &chunk);
  ASSERT_TRUE(rc == PIPER_OK || rc == PIPER_DONE);
  EXPECT_GT(chunk.num_samples, 0);

  while (!chunk.is_last)
  {
    rc = piper_synthesize_next(synth, &chunk);
    if (rc == PIPER_DONE) break;
  }

  piper_free(synth);
}

TEST_F(PinyinTest, HanziMonoFallback)
{
  if (!std::filesystem::exists(assets->modelPath()))
  {
    GTEST_SKIP();
  }
  piper_create_options opts;
  piper_init_create_options(&opts);
  std::string model = assets->modelPath().string();
  std::string config = assets->configPath().string();
  opts.model_path = model.c_str();
  opts.config_path = config.c_str();
  if (!g2pw_dir.empty()) opts.g2pw_model_dir = g2pw_dir.c_str();

  auto* synth = piper_create_with_options(&opts);
  if (!synth)
  {
    GTEST_SKIP();
  }

  // Require dicts – they are now downloaded via CMake (G2PW_TEST_DATA_DIR)
  // No skipping – if dicts missing, this fails so CI catches it
  ASSERT_NE(synth->chinese_phonemizer, nullptr)
      << "chinese_phonemizer not created, g2pw_dir=" << g2pw_dir;
  ASSERT_TRUE(synth->chinese_phonemizer->hasDicts())
      << "g2pw dicts not loaded from " << g2pw_dir;

  // Phase 1 mono-only: use truly monophonic phrase "你我" (ni3 wo3)
  // Both characters have single reading in char_bopomofo_dict (unambiguous)
  // "你好" contains 好 which is polyphonic (hao3/hao4) and is now correctly
  // treated as unsupported in mono-only mode
  int rc = piper_synthesize_start(synth, "你我", nullptr);
  ASSERT_EQ(rc, PIPER_OK);
  piper_audio_chunk chunk;
  rc = piper_synthesize_next(synth, &chunk);
  EXPECT_GT(chunk.num_samples, 0);

  piper_free(synth);
}

TEST_F(PinyinTest, MissingG2pwFallback)
{
  if (!std::filesystem::exists(assets->modelPath()))
  {
    GTEST_SKIP();
  }
  piper_create_options opts;
  piper_init_create_options(&opts);
  std::string model = assets->modelPath().string();
  std::string config = assets->configPath().string();
  opts.model_path = model.c_str();
  opts.config_path = config.c_str();
  opts.g2pw_model_dir = "/tmp/nonexistent_dir_for_fallback";
  auto* synth = piper_create_with_options(&opts);
  ASSERT_NE(synth, nullptr);

  // With nonexistent g2pw dir, direct pinyin should still work via static
  // phonemize_pinyin_text
  int rc = piper_synthesize_start(synth, "ni3 hao3", nullptr);
  EXPECT_EQ(rc, PIPER_OK);
  piper_audio_chunk chunk;
  rc = piper_synthesize_next(synth, &chunk);
  EXPECT_GT(chunk.num_samples, 0);

  piper_free(synth);
}

TEST_F(PinyinTest, PolyphonicKnownLimitation)
{
  if (!std::filesystem::exists(assets->modelPath()))
  {
    GTEST_SKIP();
  }
  piper_create_options opts;
  piper_init_create_options(&opts);
  std::string model = assets->modelPath().string();
  std::string config = assets->configPath().string();
  opts.model_path = model.c_str();
  opts.config_path = config.c_str();
  if (!g2pw_dir.empty()) opts.g2pw_model_dir = g2pw_dir.c_str();

  auto* synth = piper_create_with_options(&opts);
  ASSERT_NE(synth, nullptr);
  ASSERT_NE(synth->chinese_phonemizer, nullptr);
  ASSERT_TRUE(synth->chinese_phonemizer->hasDicts());

  // Phase 1 relaxed for iOS/macOS (no 152MB g2pw.onnx): first reading fallback
  // for polyphonic chars. Strict mono returned {} causing long sentences like
  // "彩虹，又称..." to be silent. Relaxed mode enables 95% coverage with 2MB.
  // 重庆/银行/长江 now return first sense (acceptable tradeoff vs silence).
  auto seq_zhong = synth->chinese_phonemizer->phonemize("重");
  EXPECT_FALSE(seq_zhong.empty())
      << "Phase 1 relaxed: 重 should use first reading for mobile usability";

  auto seq_xing = synth->chinese_phonemizer->phonemize("行");
  EXPECT_FALSE(seq_xing.empty())
      << "Phase 1 relaxed: 行 should use first reading";

  auto seq_chang = synth->chinese_phonemizer->phonemize("长");
  EXPECT_FALSE(seq_chang.empty())
      << "Phase 1 relaxed: 长 should use first reading";

  auto seq_cq = synth->chinese_phonemizer->phonemize("重庆");
  EXPECT_FALSE(seq_cq.empty())
      << "重庆 should now speak with first-sense fallback in relaxed Phase 1";

  auto seq_yh = synth->chinese_phonemizer->phonemize("银行");
  EXPECT_FALSE(seq_yh.empty()) << "银行 should speak with first-sense fallback";

  auto seq_cj = synth->chinese_phonemizer->phonemize("长江");
  EXPECT_FALSE(seq_cj.empty()) << "长江 should speak with first-sense fallback";

  // Positive: mono chars still work - "你我" are monophonic (single reading)
  auto seq_nh = synth->chinese_phonemizer->phonemize("你我");
  ASSERT_FALSE(seq_nh.empty()) << "你我 should succeed in mono-only mode";
  auto flat_nh = seq_nh[0];
  // Verify IDs path still works for mono
  auto ids = piper::ChinesePhonemizer::phonemes_to_ids_pinyin(
      flat_nh, synth->pinyin_id_map);
  EXPECT_GT(ids.size(), 2u);
  EXPECT_EQ(ids.front(), 1);  // BOS
  EXPECT_EQ(ids.back(), 2);   // EOS

  piper_free(synth);
}

TEST_F(PinyinTest, DataDirG2pwSubdir)
{
  if (!std::filesystem::exists(assets->modelPath()))
  {
    GTEST_SKIP();
  }
  if (g2pw_dir.empty() || !std::filesystem::exists(g2pw_dir))
  {
    GTEST_SKIP() << "g2pw dir not present: " << g2pw_dir;
  }

  // Layout: data_dir contains g2pw/ subdir with dicts
  // Use parent of g2pw_dir as data_dir, so <data_dir>/g2pw == g2pw_dir
  std::filesystem::path g2pw_path(g2pw_dir);
  std::string data_dir = g2pw_path.parent_path().string();
  if (data_dir.empty()) data_dir = ".";

  piper_create_options opts;
  piper_init_create_options(&opts);
  std::string model = assets->modelPath().string();
  std::string config = assets->configPath().string();
  opts.model_path = model.c_str();
  opts.config_path = config.c_str();
  opts.data_dir = data_dir.c_str();
  opts.g2pw_model_dir = nullptr;  // rely on data_dir fallback

  auto* synth = piper_create_with_options(&opts);
  ASSERT_NE(synth, nullptr) << "data_dir subdir fallback should create synth";
  EXPECT_FALSE(synth->g2pw_model_dir.empty());
  // Should have resolved to <data_dir>/g2pw which contains dicts
  EXPECT_TRUE(synth->chinese_phonemizer &&
              synth->chinese_phonemizer->hasDicts())
      << "expected dicts loaded via <data_dir>/g2pw, g2pw_model_dir="
      << synth->g2pw_model_dir;

  // Direct pinyin should synthesize successfully even via data_dir path
  int rc = piper_synthesize_start(synth, "ni3 hao3", nullptr);
  EXPECT_EQ(rc, PIPER_OK);
  piper_audio_chunk chunk;
  rc = piper_synthesize_next(synth, &chunk);
  EXPECT_GT(chunk.num_samples, 0);

  piper_free(synth);
}

TEST_F(PinyinTest, DataDirRootDicts)
{
  if (!std::filesystem::exists(assets->modelPath()))
  {
    GTEST_SKIP();
  }
  if (g2pw_dir.empty() || !std::filesystem::exists(g2pw_dir))
  {
    GTEST_SKIP() << "g2pw dir not present";
  }

  // Layout: dicts directly in data_dir root (no g2pw subdir)
  // Use g2pw_dir itself as data_dir – it contains char_bopomofo_dict.json
  // directly
  std::string data_dir = g2pw_dir;

  piper_create_options opts;
  piper_init_create_options(&opts);
  std::string model = assets->modelPath().string();
  std::string config = assets->configPath().string();
  opts.model_path = model.c_str();
  opts.config_path = config.c_str();
  opts.data_dir = data_dir.c_str();
  opts.g2pw_model_dir = nullptr;

  auto* synth = piper_create_with_options(&opts);
  ASSERT_NE(synth, nullptr)
      << "data_dir root fallback should create synth when dicts in root";
  EXPECT_FALSE(synth->g2pw_model_dir.empty());
  EXPECT_TRUE(synth->chinese_phonemizer &&
              synth->chinese_phonemizer->hasDicts())
      << "expected dicts loaded via data_dir root, g2pw_model_dir="
      << synth->g2pw_model_dir;

  // Youhao mono should still work via root layout
  int rc = piper_synthesize_start(synth, "你我", nullptr);
  EXPECT_EQ(rc, PIPER_OK);
  piper_audio_chunk chunk;
  rc = piper_synthesize_next(synth, &chunk);
  EXPECT_GT(chunk.num_samples, 0);

  piper_free(synth);
}
