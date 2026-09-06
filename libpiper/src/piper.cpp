#define BUILDING_LIBPIPER
#include "piper.h"

#include <array>
#include <cstddef>
#include <filesystem>
#include <fstream>
#include <limits>
#include <unordered_map>

#include "piper_impl.hpp"

#ifdef WIN32
#define WIN32_LEAN_AND_MEAN
#if !defined(NOMINMAX)
#define NOMINMAX
#endif
#include <windows.h>         // for MultiByteToWideChar below
#define LIBESPEAK_NG_EXPORT  // espeak is exported from piper dll
#endif

#ifndef PIPER_VERSION
#define PIPER_VERSION "0.0.1"
#endif

#include <espeak-ng/speak_lib.h>

using json = nlohmann::json;

auto piper_create_with_options(const piper_create_options* options)
    -> struct piper_synthesizer*
{
  // onnx
  static Ort::Env ort_env{ORT_LOGGING_LEVEL_WARNING, "piper"};

  if (options == nullptr)
  {
    return nullptr;
  }

  // Basic version check - allow forward compatible larger structs
  if (options->struct_size < offsetof(piper_create_options, espeak_data_path) +
                                 sizeof(options->espeak_data_path))
  {
    // Struct too small to contain required fields
    return nullptr;
  }

  const char* model_path = options->model_path;
  const char* config_path = options->config_path;
  const char* espeak_data_path = options->espeak_data_path;
  const char* g2pw_model_dir_opt = nullptr;
  const char* data_dir_opt = nullptr;

  // Read newer fields if struct is large enough
  if (options->struct_size >= offsetof(piper_create_options, g2pw_model_dir) +
                                  sizeof(options->g2pw_model_dir))
  {
    g2pw_model_dir_opt = options->g2pw_model_dir;
  }
  if (options->struct_size >=
      offsetof(piper_create_options, data_dir) + sizeof(options->data_dir))
  {
    data_dir_opt = options->data_dir;
  }

  // Resolve espeak_data_path via data_dir fallback
  std::string resolved_espeak_data;
  const char* final_espeak_data_path = espeak_data_path;
  if (!final_espeak_data_path && data_dir_opt)
  {
    std::string cand = std::string(data_dir_opt) + "/espeak-ng-data";
    resolved_espeak_data = cand;
    final_espeak_data_path = resolved_espeak_data.c_str();
  }

  // Resolve g2pw_model_dir via data_dir fallback (for later use)
  // NOTE: Do NOT auto-set final_g2pw_model_dir to <data_dir>/g2pw here.
  // Let effective_g2pw_dir logic below probe both <data_dir>/g2pw and
  // <data_dir> based on dict existence (MONOPHONIC_CHARS.txt /
  // char_bopomofo_dict.json). Setting it eagerly made root fallback
  // unreachable.
  std::string resolved_g2pw_dir;
  const char* final_g2pw_model_dir = g2pw_model_dir_opt;

  if (model_path == nullptr)
  {
    return nullptr;
  }

  std::string config_path_str;
  if (config_path == nullptr)
  {
    std::string model_path_str(model_path);
    config_path_str = model_path_str + ".json";
  }
  else
  {
    config_path_str = config_path;
  }

  std::ifstream config_stream(config_path_str);
  auto config = json::parse(config_stream);
  PhonemeType phoneme_type = PhonemeType::Espeak;
  if (config.contains("phoneme_type"))
  {
    phoneme_type = config["phoneme_type"].get<PhonemeType>();
  }

  if (phoneme_type == PhonemeType::Espeak &&
      espeak_Initialize(AUDIO_OUTPUT_SYNCHRONOUS, 0, final_espeak_data_path,
                        0) < 0)
  {
    return nullptr;
  }

  auto* synth = new piper_synthesizer();
  synth->phoneme_type = phoneme_type;

  // Load config options
  synth->espeak_voice = "en-us";  // default
  if (config.contains("espeak"))
  {
    auto& espeak_obj = config["espeak"];
    if (espeak_obj.contains("voice"))
    {
      synth->espeak_voice = espeak_obj["voice"].get<std::string>();
    }
  }

  if (config.contains("audio"))
  {
    auto& audio_obj = config["audio"];
    if (audio_obj.contains("sample_rate"))
    {
      synth->sample_rate = audio_obj["sample_rate"].get<int>();
    }
  }

  if (phoneme_type == PhonemeType::Pinyin)
  {
    // pinyin_id_map : string -> ids
    if (config.contains("phoneme_id_map"))
    {
      auto& m = config["phoneme_id_map"];
      for (auto& kv : m.items())
      {
        std::string key = kv.key();
        std::vector<PhonemeId> ids;
        for (auto& v : kv.value())
        {
          ids.push_back(v.get<PhonemeId>());
        }
        synth->pinyin_id_map[key] = ids;
        // also keep compatibility single char mapping if key length ==1
        if (key.size() == 1)
        {
          auto cp = get_codepoint(key);
          if (cp)
          {
            synth->phoneme_id_map[*cp] = ids;
          }
        }
        else if (key == "Ø")
        {  // U+00D8 char from json \u00d8
          // multi byte char length 2 in utf8, get_codepoint will handle
          auto cp = get_codepoint(key);
          if (cp) synth->phoneme_id_map[*cp] = ids;
        }
      }
    }
  }
  else
  {
    // phoneme to [id] map for espeak/text
    if (config.contains("phoneme_id_map"))
    {
      auto& phoneme_id_map_value = config["phoneme_id_map"];
      for (const auto& from_phoneme_item : phoneme_id_map_value.items())
      {
        const std::string& from_phoneme = from_phoneme_item.key();
        auto from_codepoint = get_codepoint(from_phoneme);
        if (!from_codepoint)
        {
          continue;
        }
        for (auto& to_id_value : from_phoneme_item.value())
        {
          PhonemeId to_id = to_id_value.get<PhonemeId>();
          synth->phoneme_id_map[*from_codepoint].push_back(to_id);
        }
      }
    }
  }

  synth->num_speakers = config["num_speakers"].get<SpeakerId>();

  if (config.contains("inference"))
  {
    auto inference_value = config["inference"];
    if (inference_value.contains("noise_scale"))
    {
      synth->synth_noise_scale = inference_value["noise_scale"].get<float>();
    }
    if (inference_value.contains("length_scale"))
    {
      synth->synth_length_scale = inference_value["length_scale"].get<float>();
    }
    if (inference_value.contains("noise_w"))
    {
      synth->synth_noise_w_scale = inference_value["noise_w"].get<float>();
    }
  }

  std::string effective_g2pw_dir;
  if (final_g2pw_model_dir && final_g2pw_model_dir[0] != '\0')
  {
    effective_g2pw_dir = final_g2pw_model_dir;
  }
  if (effective_g2pw_dir.empty() && data_dir_opt)
  {
    // Phase 1: check for mono dicts, not g2pw.onnx (deferred to Phase 2)
    // Readiness requires a pronunciation source (MONOPHONIC_CHARS.txt or
    // char_bopomofo_dict.json) AND bopomofo_to_pinyin_wo_tune_dict.json.
    // Try <data_dir>/g2pw first, then <data_dir> root as fallback (documented)
    std::filesystem::path cand1 = std::filesystem::path(data_dir_opt) / "g2pw";
    std::filesystem::path cand2 = std::filesystem::path(data_dir_opt);
    auto has_dicts = [](const std::filesystem::path& d)
    {
      bool has_source = std::filesystem::exists(d / "MONOPHONIC_CHARS.txt") ||
                        std::filesystem::exists(d / "char_bopomofo_dict.json");
      bool has_b2p =
          std::filesystem::exists(d / "bopomofo_to_pinyin_wo_tune_dict.json");
      return has_source && has_b2p;
    };
    if (has_dicts(cand1))
    {
      effective_g2pw_dir = cand1.string();
    }
    else if (has_dicts(cand2))
    {
      effective_g2pw_dir = cand2.string();
    }
    else if (std::filesystem::exists(cand1))
    {
      // cand1 exists but without complete dicts - still prefer it for
      // backward compat if it at least has a source (load() will verify
      // completeness and report failure)
      if (std::filesystem::exists(cand1 / "MONOPHONIC_CHARS.txt") ||
          std::filesystem::exists(cand1 / "char_bopomofo_dict.json"))
      {
        effective_g2pw_dir = cand1.string();
      }
      else
      {
        effective_g2pw_dir = cand1.string();
      }
    }
    else
    {
      // default to <data_dir>/g2pw even if not existing yet - will be
      // non-fatal and phonemizer will load what it can, keeping direct pinyin
      // path working
      effective_g2pw_dir = cand1.string();
    }
  }
  if (effective_g2pw_dir.empty() && phoneme_type == PhonemeType::Pinyin)
  {
    std::filesystem::path model_path_fs(model_path);
    std::filesystem::path model_dir = model_path_fs.parent_path();
    std::vector<std::filesystem::path> fallbacks = {
        model_dir / "g2pw",
        std::filesystem::path("./g2pw"),
        std::filesystem::path("./local/g2pw"),
        std::filesystem::path("local/g2pw"),
    };
    for (auto& p : fallbacks)
    {
      bool has_source = std::filesystem::exists(p / "MONOPHONIC_CHARS.txt") ||
                        std::filesystem::exists(p / "char_bopomofo_dict.json");
      bool has_b2p =
          std::filesystem::exists(p / "bopomofo_to_pinyin_wo_tune_dict.json");
      if (has_source && has_b2p)
      {
        effective_g2pw_dir = p.string();
        break;
      }
    }
    if (effective_g2pw_dir.empty())
    {
      effective_g2pw_dir = (model_dir / "g2pw").string();
    }
  }
  synth->g2pw_model_dir = effective_g2pw_dir;

  if (phoneme_type == PhonemeType::Pinyin)
  {
    // attempt to load chinese phonemizer dicts (non-fatal)
    // Phase 1: monophonic fallback only; g2pw BERT deferred
    try
    {
      if (!synth->g2pw_model_dir.empty())
      {
        auto ph = std::make_unique<piper::ChinesePhonemizer>();
        if (ph->load(synth->g2pw_model_dir))
        {
          synth->chinese_phonemizer = std::move(ph);
        }
        else
        {
          // still keep instance for pinyin direct
          synth->chinese_phonemizer = std::move(ph);
        }
      }
    }
    catch (...)
    {
    }
  }

  // Load onnx model
  synth->session_options.DisableCpuMemArena();
  synth->session_options.DisableMemPattern();
  synth->session_options.DisableProfiling();
  synth->session_options.SetIntraOpNumThreads(1);
  synth->session_options.SetInterOpNumThreads(1);
  synth->session_options.SetGraphOptimizationLevel(
      GraphOptimizationLevel::ORT_ENABLE_BASIC);
  synth->session_options.SetExecutionMode(ExecutionMode::ORT_SEQUENTIAL);

#if !defined(WIN32)
  const auto* model_path_ort = model_path;
#else
  auto sz = ::MultiByteToWideChar(CP_ACP, 0, model_path, -1, 0, 0);
  std::vector<wchar_t> model_path_wc(sz + 1);
  ::MultiByteToWideChar(CP_ACP, 0, model_path, -1, &model_path_wc[0], sz);
  auto model_path_ort = &model_path_wc[0];
#endif
  synth->session = std::make_unique<Ort::Session>(
      Ort::Session(ort_env, model_path_ort, synth->session_options));

  return synth;
}

auto piper_create(const char* model_path, const char* config_path,
                  const char* espeak_data_path) -> struct piper_synthesizer*
{
  piper_create_options opts;
  piper_init_create_options(&opts);
  opts.model_path = model_path;
  opts.config_path = config_path;
  opts.espeak_data_path = espeak_data_path;
  return piper_create_with_options(&opts);
}

void piper_free(struct piper_synthesizer* synth)
{
  if (synth == nullptr)
  {
    return;
  }
  if (synth->phoneme_type == PhonemeType::Espeak)
  {
    espeak_Terminate();
  }
  delete synth;
}

auto piper_default_synthesize_options(piper_synthesizer* synth)
    -> piper_synthesize_options
{
  piper_synthesize_options options;
  options.speaker_id = 0;
  options.length_scale = DEFAULT_LENGTH_SCALE;
  options.noise_scale = DEFAULT_NOISE_SCALE;
  options.noise_w_scale = DEFAULT_NOISE_W_SCALE;

  if (synth != nullptr)
  {
    options.length_scale = synth->synth_length_scale;
    options.noise_scale = synth->synth_noise_scale;
    options.noise_w_scale = synth->synth_noise_w_scale;
  }

  return options;
}

// helper for pinyin fake codepoints
static Phoneme fake_cp_for_pinyin(
    const std::string& s, std::unordered_map<std::string, Phoneme>& cache,
    Phoneme& next_private)
{
  auto it = cache.find(s);
  if (it != cache.end()) return it->second;
  Phoneme cp = 0;
  if (s == "^")
    cp = U'^';
  else if (s == "_")
    cp = U'_';
  else if (s == "$")
    cp = U'$';
  else if (s == " ")
    cp = U' ';
  else if (s.size() == 1)
  {
    cp = static_cast<Phoneme>(static_cast<unsigned char>(s[0]));
  }
  else if (s == "Ø" || s == "\xC3\x98")
  {
    cp = 0x00D8;
  }
  else
  {
    cp = next_private++;
    if (next_private > 0xF8FF) next_private = 0xE000;
  }
  cache[s] = cp;
  return cp;
}

auto piper_synthesize_start(struct piper_synthesizer* synth, const char* text,
                            const piper_synthesize_options* options) -> int
{
  if (synth == nullptr)
  {
    return PIPER_ERR_GENERIC;
  }

  if (synth->phoneme_type == PhonemeType::Espeak &&
      espeak_SetVoiceByName(synth->espeak_voice.c_str()) != EE_OK)
  {
    return PIPER_ERR_GENERIC;
  }

  // Clear state
  while (!synth->phoneme_id_queue.empty())
  {
    synth->phoneme_id_queue.pop();
  }
  synth->chunk_samples.clear();

  std::unique_ptr<piper_synthesize_options> default_options;
  if (options == nullptr)
  {
    default_options = std::make_unique<piper_synthesize_options>(
        piper_default_synthesize_options(synth));
    options = default_options.get();
  }

  synth->length_scale = options->length_scale;
  synth->noise_scale = options->noise_scale;
  synth->noise_w_scale = options->noise_w_scale;
  synth->speaker_id = options->speaker_id;

  // phonemize (single dispatch)
  std::vector<std::string> sentence_phonemes{""};
  switch (synth->phoneme_type)
  {
  case PhonemeType::Pinyin:
  {
    if (synth->pinyin_id_map.empty())
    {
      return PIPER_ERR_GENERIC;
    }

    std::vector<std::vector<std::string>> sentences_str;

    if (synth->chinese_phonemizer)
    {
      try
      {
        auto s = synth->chinese_phonemizer->phonemize(text);
        if (!s.empty())
        {
          sentences_str = std::move(s);
        }
        else
        {
          sentences_str = piper::ChinesePhonemizer::phonemize_pinyin_text(text);
        }
      }
      catch (...)
      {
        sentences_str = piper::ChinesePhonemizer::phonemize_pinyin_text(text);
      }
    }
    else
    {
      sentences_str = piper::ChinesePhonemizer::phonemize_pinyin_text(text);
    }

    if (sentences_str.empty())
    {
      return PIPER_ERR_GENERIC;
    }

    std::unordered_map<std::string, Phoneme> cp_cache;
    Phoneme next_private = 0xE000;

    for (auto& ph_seq : sentences_str)
    {
      if (ph_seq.empty()) continue;

      std::vector<Phoneme> sent_cps;
      std::vector<PhonemeId> sent_ids;
      sent_cps.reserve(ph_seq.size() * 3 + 4);
      sent_ids.reserve(ph_seq.size() * 2 + 4);

      // BOS block
      {
        std::string bos = "^";
        auto it = synth->pinyin_id_map.find(bos);
        if (it != synth->pinyin_id_map.end())
        {
          for (auto idv : it->second)
          {
            sent_cps.push_back(fake_cp_for_pinyin(bos, cp_cache, next_private));
            sent_ids.push_back(idv);
          }
        }
        else
        {
          sent_cps.push_back(U'^');
          sent_ids.push_back(ID_BOS);
        }
        sent_cps.push_back(0);  // separator
      }

      for (auto& ph : ph_seq)
      {
        auto it = synth->pinyin_id_map.find(ph);
        if (it == synth->pinyin_id_map.end())
        {
          // skip unknown but allow space/punct fallback: if ph length 1 char
          // maybe?
          continue;
        }
        Phoneme cp = fake_cp_for_pinyin(ph, cp_cache, next_private);
        for (auto idv : it->second)
        {
          sent_cps.push_back(cp);
          sent_ids.push_back(idv);
        }
        // Pad after GROUP_END phonemes
        if (piper::GROUP_END_PHONEMES.find(ph) !=
            piper::GROUP_END_PHONEMES.end())
        {
          auto it_pad = synth->pinyin_id_map.find("_");
          if (it_pad != synth->pinyin_id_map.end())
          {
            for (auto pid : it_pad->second)
            {
              sent_cps.push_back(cp);  // reuse ph cp for pad representation
              sent_ids.push_back(pid);
            }
          }
          else
          {
            sent_cps.push_back(cp);
            sent_ids.push_back(ID_PAD);
          }
        }
        sent_cps.push_back(0);  // separator after each phoneme block
      }

      // EOS
      {
        std::string eos = "$";
        auto it = synth->pinyin_id_map.find(eos);
        if (it != synth->pinyin_id_map.end())
        {
          for (auto idv : it->second)
          {
            sent_cps.push_back(fake_cp_for_pinyin(eos, cp_cache, next_private));
            sent_ids.push_back(idv);
          }
        }
        else
        {
          sent_cps.push_back(U'$');
          sent_ids.push_back(ID_EOS);
        }
        sent_cps.push_back(0);
      }

      if (!sent_ids.empty())
      {
        synth->phoneme_id_queue.emplace(std::move(sent_cps),
                                        std::move(sent_ids));
      }
    }

    return synth->phoneme_id_queue.empty() ? PIPER_ERR_GENERIC : PIPER_OK;
  }
  case PhonemeType::Espeak:
  {
    std::size_t current_idx = 0;
    const void* text_ptr = text;
    while (text_ptr != nullptr)
    {
      int terminator = 0;
      std::string terminator_str;

      const char* phonemes = espeak_TextToPhonemesWithTerminator(
          &text_ptr, espeakCHARS_AUTO, espeakPHONEMES_IPA, &terminator);

      if (phonemes != nullptr)
      {
        sentence_phonemes[current_idx] += phonemes;
      }

      terminator &= 0x000FFFFF;

      if (terminator == CLAUSE_PERIOD)
      {
        terminator_str = ".";
      }
      else if (terminator == CLAUSE_QUESTION)
      {
        terminator_str = "?";
      }
      else if (terminator == CLAUSE_EXCLAMATION)
      {
        terminator_str = "!";
      }
      else if (terminator == CLAUSE_COMMA)
      {
        terminator_str = ", ";
      }
      else if (terminator == CLAUSE_COLON)
      {
        terminator_str = ": ";
      }
      else if (terminator == CLAUSE_SEMICOLON)
      {
        terminator_str = "; ";
      }

      sentence_phonemes[current_idx] += terminator_str;

      if ((terminator & CLAUSE_TYPE_SENTENCE) == CLAUSE_TYPE_SENTENCE)
      {
        sentence_phonemes.emplace_back("");
        current_idx = sentence_phonemes.size() - 1;
      }
    }
    break;
  }
  case PhonemeType::Text:
  {
    std::string lower_text = una::cases::to_lowercase_utf8(text);
    std::string nfd_text = una::norm::to_nfd_utf8(lower_text);
    sentence_phonemes.clear();
    sentence_phonemes.push_back(nfd_text);
    break;
  }
  case PhonemeType::Invalid:
  {
    return PIPER_ERR_GENERIC;
  }
  }

  // phonemes to ids for Espeak/Text
  std::vector<Phoneme> sentence_codepoints;
  std::vector<PhonemeId> sentence_ids;
  for (auto& phonemes_str : sentence_phonemes)
  {
    if (phonemes_str.empty())
    {
      continue;
    }

    sentence_codepoints.push_back(PHONEME_BOS);
    sentence_ids.push_back(ID_BOS);

    sentence_codepoints.push_back(PHONEME_BOS);
    sentence_ids.push_back(ID_PAD);

    sentence_codepoints.push_back(PHONEME_SEPARATOR);

    auto phonemes_norm = una::norm::to_nfd_utf8(phonemes_str);
    auto phonemes_range = una::ranges::utf8_view{phonemes_norm};
    auto phonemes_iter = phonemes_range.begin();
    auto phonemes_end = phonemes_range.end();

    bool in_lang_flag = false;
    while (phonemes_iter != phonemes_end)
    {
      auto phoneme = *phonemes_iter;

      if (in_lang_flag)
      {
        if (phoneme == U')')
        {
          in_lang_flag = false;
        }
      }
      else if (phoneme == U'(')
      {
        in_lang_flag = true;
      }
      else
      {
        auto ids_for_phoneme = synth->phoneme_id_map.find(phoneme);
        if (ids_for_phoneme != synth->phoneme_id_map.end())
        {
          for (auto identifier : ids_for_phoneme->second)
          {
            sentence_codepoints.push_back(phoneme);
            sentence_ids.push_back(identifier);

            sentence_codepoints.push_back(phoneme);
            sentence_ids.push_back(ID_PAD);

            sentence_codepoints.push_back(PHONEME_SEPARATOR);
          }
        }
      }

      phonemes_iter++;
    }

    sentence_codepoints.push_back(PHONEME_EOS);
    sentence_ids.push_back(ID_EOS);
    sentence_codepoints.push_back(PHONEME_SEPARATOR);

    synth->phoneme_id_queue.emplace(
        std::move(std::make_pair(sentence_codepoints, sentence_ids)));
    sentence_ids.clear();
  }

  return PIPER_OK;
}

auto piper_synthesize_next(struct piper_synthesizer* synth,
                           struct piper_audio_chunk* chunk) -> int
{
  if (synth == nullptr)
  {
    return PIPER_ERR_GENERIC;
  }

  if (chunk == nullptr)
  {
    return PIPER_ERR_GENERIC;
  }

  synth->chunk_samples.clear();
  synth->chunk_phonemes.clear();
  synth->chunk_phoneme_ids.clear();
  synth->chunk_alignments.clear();

  chunk->sample_rate = synth->sample_rate;
  chunk->samples = nullptr;
  chunk->num_samples = 0;
  chunk->is_last = false;
  chunk->phoneme_ids = nullptr;
  chunk->num_phoneme_ids = 0;
  chunk->alignments = nullptr;
  chunk->num_alignments = 0;

  if (synth->phoneme_id_queue.empty())
  {
    chunk->is_last = true;
    return PIPER_DONE;
  }

  auto [next_phonemes, next_ids] = std::move(synth->phoneme_id_queue.front());
  synth->phoneme_id_queue.pop();

  auto memoryInfo = Ort::MemoryInfo::CreateCpu(
      OrtAllocatorType::OrtDeviceAllocator, OrtMemType::OrtMemTypeDefault);

  std::vector<int64_t> phoneme_id_lengths{
      static_cast<int64_t>(next_ids.size())};
  std::vector<float> scales{synth->noise_scale, synth->length_scale,
                            synth->noise_w_scale};

  std::vector<Ort::Value> input_tensors;
  std::vector<int64_t> phoneme_ids_shape{1,
                                         static_cast<int64_t>(next_ids.size())};
  input_tensors.push_back(Ort::Value::CreateTensor<int64_t>(
      memoryInfo, next_ids.data(), next_ids.size(), phoneme_ids_shape.data(),
      phoneme_ids_shape.size()));

  std::vector<int64_t> phoneme_id_lengths_shape{
      static_cast<int64_t>(phoneme_id_lengths.size())};
  input_tensors.push_back(Ort::Value::CreateTensor<int64_t>(
      memoryInfo, phoneme_id_lengths.data(), phoneme_id_lengths.size(),
      phoneme_id_lengths_shape.data(), phoneme_id_lengths_shape.size()));

  std::vector<int64_t> scales_shape{static_cast<int64_t>(scales.size())};
  input_tensors.push_back(Ort::Value::CreateTensor<float>(
      memoryInfo, scales.data(), scales.size(), scales_shape.data(),
      scales_shape.size()));

  std::vector<int64_t> speaker_id{static_cast<int64_t>(synth->speaker_id)};
  std::vector<int64_t> speaker_id_shape{
      static_cast<int64_t>(speaker_id.size())};

  if (synth->num_speakers > 1)
  {
    input_tensors.push_back(Ort::Value::CreateTensor<int64_t>(
        memoryInfo, speaker_id.data(), speaker_id.size(),
        speaker_id_shape.data(), speaker_id_shape.size()));
  }

  std::array<const char*, 4> input_names = {"input", "input_lengths", "scales",
                                            "sid"};

  std::vector<std::string> output_names_strs = synth->session->GetOutputNames();
  std::vector<const char*> output_names;
  output_names.reserve(output_names_strs.size());
  for (const auto& name : output_names_strs)
  {
    output_names.push_back(name.c_str());
  }

  auto output_tensors = synth->session->Run(
      Ort::RunOptions{nullptr}, input_names.data(), input_tensors.data(),
      input_tensors.size(), output_names.data(), output_names.size());

  if ((output_tensors.empty()) || (!output_tensors.front().IsTensor()))
  {
    return PIPER_ERR_GENERIC;
  }

  auto audio_shape =
      output_tensors.front().GetTensorTypeAndShapeInfo().GetShape();
  chunk->num_samples = audio_shape[audio_shape.size() - 1];

  const auto* audio_tensor_data = output_tensors.front().GetTensorData<float>();
  synth->chunk_samples.resize(chunk->num_samples);
  std::copy(audio_tensor_data, audio_tensor_data + chunk->num_samples,
            synth->chunk_samples.begin());
  chunk->samples = synth->chunk_samples.data();

  chunk->is_last = synth->phoneme_id_queue.empty();

  synth->chunk_phonemes = std::move(next_phonemes);
  chunk->phonemes = synth->chunk_phonemes.data();
  chunk->num_phonemes = synth->chunk_phonemes.size();

  for (auto phoneme_id : next_ids)
  {
    if (phoneme_id < std::numeric_limits<int>::min() ||
        phoneme_id > std::numeric_limits<int>::max())
    {
      continue;
    }
    synth->chunk_phoneme_ids.push_back(static_cast<int>(phoneme_id));
  }

  chunk->phoneme_ids = synth->chunk_phoneme_ids.data();
  chunk->num_phoneme_ids = synth->chunk_phoneme_ids.size();

  if (output_tensors.size() > 1)
  {
    auto alignments_shape =
        output_tensors[1].GetTensorTypeAndShapeInfo().GetShape();

    chunk->num_alignments = alignments_shape[alignments_shape.size() - 1];
    const auto* alignments_tensor_data =
        output_tensors[1].GetTensorData<float>();

    synth->chunk_alignments.resize(chunk->num_alignments);
    for (std::size_t i = 0; i < chunk->num_alignments; i++)
    {
      synth->chunk_alignments[i] =
          static_cast<int>(alignments_tensor_data[i] * synth->hop_length);
    }

    chunk->alignments = synth->chunk_alignments.data();
  }

  for (auto& output_tensor : output_tensors)
  {
    Ort::detail::OrtRelease(output_tensor.release());
  }

  for (auto& input_tensor : input_tensors)
  {
    Ort::detail::OrtRelease(input_tensor.release());
  }

  return chunk->is_last ? PIPER_DONE : PIPER_OK;
}

auto piper_version(void) -> char const*
{
  return PIPER_VERSION;
}
