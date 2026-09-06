#include "chinese_phonemizer.h"

#include <algorithm>
#include <cctype>
#include <fstream>
#include <iostream>
#include <regex>
#include <sstream>

#include "json.hpp"
#include "piper_impl.hpp"
#include "uni_algo.h"

namespace piper
{

const std::vector<std::string> PINYIN_INITIALS = {"zh", "ch", "sh", "b", "p", "m", "f", "d", "t", "n", "l", "g",
                                                  "k",  "h",  "j",  "q", "x", "r", "z", "c", "s", "y", "w"};

const std::set<std::string> GROUP_END_PHONEMES = {"1", "2", "3",  "4",  "5",  "。", "？", "！", ".", "?", "!",
                                                  "—", "…", "、", "，", "：", "；", ",",  ":",  ";", " ", "\n"};

const std::set<std::string> PINYIN_PUNCTUATIONS = {".",  "?",  "!",  ",",  ":",  ";", "，", "。",
                                                   "？", "！", "、", "：", "；", "—", "…",  " "};

std::string normalize_g2pw_syllable(const std::string& syl)
{
  if (syl.empty()) return syl;
  char last = syl.back();
  if (last < '1' || last > '5') return syl;
  std::string base = syl.substr(0, syl.size() - 1);
  if (base.empty()) return syl;

  // Replace u: -> v
  std::string t = base;
  // replace "u:"
  size_t pos = 0;
  while ((pos = t.find("u:", pos)) != std::string::npos)
  {
    t.replace(pos, 2, "v");
    pos += 1;
  }
  // replace ü (utf8 C3 BC)
  const std::string uv = "ü";  // utf8 literal
  pos = 0;
  while ((pos = t.find(uv, pos)) != std::string::npos)
  {
    t.replace(pos, uv.size(), "v");
    pos += 1;
  }

  // validate remaining consists of a-z and v only (after replacement)
  for (size_t i = 0; i < t.size();)
  {
    unsigned char c = static_cast<unsigned char>(t[i]);
    if (c < 128)
    {
      if ((c >= 'a' && c <= 'z') || c == 'v')
      {
        ++i;
        continue;
      }
      return syl;  // contains invalid char
    }
    else
    {
      // multibyte char not allowed after replacement
      return syl;
    }
  }

  return t + std::string(1, last);
}

std::tuple<std::string, std::string, std::string> split_initial_final_tone(const std::string& syl)
{
  if (syl.empty()) return {"", "", ""};
  // pattern ^([a-zvü]+)([1-5])$
  // Since after normalize we have no ü or :, we allow a-z and v
  char tone_c = syl.back();
  if (tone_c < '1' || tone_c > '5') return {"", "", ""};
  std::string base = syl.substr(0, syl.size() - 1);
  std::string tone(1, tone_c);

  // base must be non-empty and only a-zv
  if (base.empty()) return {"", "", ""};
  for (char ch : base)
  {
    if (!((ch >= 'a' && ch <= 'z') || ch == 'v'))
    {
      // allow also ü? but after normalize shouldn't appear
      if (static_cast<unsigned char>(ch) >= 128) return {"", "", ""};
      // if char not allowed, fail
      if (ch < 'a' || ch > 'z') return {"", "", ""};
    }
  }

  std::string ini;
  std::string left = base;
  for (const auto& cand : PINYIN_INITIALS)
  {
    if (left.rfind(cand, 0) == 0)
    {  // starts_with
      ini = cand;
      left = left.substr(cand.size());
      break;
    }
  }
  std::string fin = left;
  return {ini, fin, tone};
}

std::optional<char32_t> get_codepoint_str(const std::string& s)
{
  if (s.empty()) return std::nullopt;
  auto view = una::views::utf8(s);
  auto it = view.begin();
  if (it == view.end()) return std::nullopt;
  char32_t cp = *it;
  ++it;
  if (it != view.end()) return std::nullopt;  // more than one codepoint
  return cp;
}

std::vector<int64_t> phonemes_to_ids(const std::vector<std::string>& phonemes,
                                     const std::map<std::string, std::vector<int64_t>>& id_map)
{
  std::vector<int64_t> ids;
  auto it_bos = id_map.find("^");
  if (it_bos != id_map.end())
    ids.insert(ids.end(), it_bos->second.begin(), it_bos->second.end());
  else
    ids.push_back(ID_BOS);

  auto it_pad = id_map.find("_");
  std::vector<int64_t> pad_ids;
  if (it_pad != id_map.end())
    pad_ids = it_pad->second;
  else
    pad_ids = {ID_PAD};

  auto it_eos = id_map.find("$");
  std::vector<int64_t> eos_ids;
  if (it_eos != id_map.end())
    eos_ids = it_eos->second;
  else
    eos_ids = {ID_EOS};

  for (const auto& ph : phonemes)
  {
    auto it = id_map.find(ph);
    if (it == id_map.end())
    {
      // unknown phoneme, skip with warning if not whitespace
      if (ph != " " && ph != "\n" && !ph.empty())
      {
        // std::cerr << "Missing id for phoneme " << ph << "\n";
      }
      continue;
    }
    ids.insert(ids.end(), it->second.begin(), it->second.end());
    if (GROUP_END_PHONEMES.find(ph) != GROUP_END_PHONEMES.end())
    {
      ids.insert(ids.end(), pad_ids.begin(), pad_ids.end());
    }
  }
  ids.insert(ids.end(), eos_ids.begin(), eos_ids.end());
  return ids;
}

bool ChinesePhonemizer::load(const std::string& g2pw_model_dir)
{
  using json = nlohmann::json;
  std::string base = g2pw_model_dir;
  if (!base.empty() && base.back() == '/') base.pop_back();

  // MONOPHONIC
  std::string mono_path = base + "/MONOPHONIC_CHARS.txt";
  std::ifstream mf(mono_path);
  if (mf)
  {
    std::string line;
    while (std::getline(mf, line))
    {
      if (line.empty()) continue;
      size_t tab = line.find('\t');
      if (tab == std::string::npos)
      {
        // fallback split on space
        tab = line.find(' ');
        if (tab == std::string::npos) continue;
      }
      std::string ch = line.substr(0, tab);
      std::string bopo = line.substr(tab + 1);
      // trim
      bopo.erase(0, bopo.find_first_not_of(" \t\r\n"));
      bopo.erase(bopo.find_last_not_of(" \t\r\n") + 1);
      ch.erase(0, ch.find_first_not_of(" \t\r\n"));
      ch.erase(ch.find_last_not_of(" \t\r\n") + 1);
      if (!ch.empty() && !bopo.empty()) mono_dict[ch] = bopo;
    }
  }

  std::string char_bopo_path = base + "/char_bopomofo_dict.json";
  std::ifstream cbf(char_bopo_path);
  if (cbf)
  {
    try
    {
      json j;
      cbf >> j;
      for (auto& el : j.items())
      {
        std::string key = el.key();
        if (el.value().is_array())
        {
          std::vector<std::string> arr;
          for (auto& x : el.value())
            if (x.is_string()) arr.push_back(x.get<std::string>());
          char_bopomofo_dict[key] = arr;
        }
      }
    }
    catch (...)
    {
    }
  }

  std::string b2p_path = base + "/bopomofo_to_pinyin_wo_tune_dict.json";
  std::ifstream b2p(b2p_path);
  if (b2p)
  {
    try
    {
      json j;
      b2p >> j;
      for (auto& el : j.items())
      {
        if (el.value().is_string()) bopomofo2pinyin[el.key()] = el.value().get<std::string>();
      }
    }
    catch (...)
    {
    }
  }

  // Phase 1 readiness requires a pronunciation source (mono table or char
  // dict) AND the bopomofo->pinyin map. bert-base-chinese_s2t_dict.txt is
  // Phase 2 only and not checked here. This prevents silent success when
  // only char_bopomofo_dict.json is present after a partial download.
  bool has_source = !mono_dict.empty() || !char_bopomofo_dict.empty();
  bool has_bopomofo_map = !bopomofo2pinyin.empty();
  has_dicts = has_source && has_bopomofo_map;
  return has_dicts;
}

std::string ChinesePhonemizer::bopomofo_to_pinyin(const std::string& bopomofo) const
{
  if (bopomofo.empty()) return "";
  char last = bopomofo.back();
  std::string base = bopomofo;
  std::string tone;
  if (last >= '1' && last <= '5')
  {
    base = bopomofo.substr(0, bopomofo.size() - 1);
    tone = std::string(1, last);
  }
  else
  {
    tone = "5";  // neutral?
  }
  auto it = bopomofo2pinyin.find(base);
  if (it == bopomofo2pinyin.end())
  {
    // try with full
    it = bopomofo2pinyin.find(bopomofo);
    if (it == bopomofo2pinyin.end()) return "";
    return normalize_g2pw_syllable(it->second + tone);
  }
  return normalize_g2pw_syllable(it->second + tone);
}

std::vector<std::vector<std::string>> ChinesePhonemizer::phonemize_pinyin_text(const std::string& text)
{
  // Lowercase
  std::string lower = text;
  std::transform(lower.begin(), lower.end(), lower.begin(), ::tolower);

  std::vector<std::string> phonemes;

  // split by whitespace
  std::istringstream iss(lower);
  std::string token;
  bool first_syl = true;
  while (iss >> token)
  {
    if (token.empty()) continue;
    // separate trailing punctuation
    std::string core = token;
    std::string trail_punct;
    while (!core.empty())
    {
      std::string last_char(1, core.back());
      if (last_char == "." || last_char == "?" || last_char == "!" || last_char == "," || last_char == ":" ||
          last_char == ";")
      {
        trail_punct = last_char + trail_punct;
        core.pop_back();
      }
      else
      {
        break;
      }
    }

    if (core.empty())
    {
      // only punct
      for (char c : trail_punct)
      {
        std::string p(1, c);
        if (PINYIN_PUNCTUATIONS.find(p) != PINYIN_PUNCTUATIONS.end()) phonemes.push_back(p);
      }
      continue;
    }

    // core is expected pinyin like ni3
    auto norm = normalize_g2pw_syllable(core);
    auto [ini, fin, tone] = split_initial_final_tone(norm);
    if (fin.empty() && ini.empty())
    {
      // try original core without normalize? Maybe direct split
      auto [ini2, fin2, tone2] = split_initial_final_tone(core);
      if (fin2.empty() && ini2.empty())
      {
        // skip unknown token
        continue;
      }
      ini = ini2;
      fin = fin2;
      tone = tone2;
    }

    if (!first_syl)
    {
      // optional short pause between syllables
      phonemes.push_back(" ");
    }
    first_syl = false;

    if (ini.empty()) ini = "Ø";
    phonemes.push_back(ini);
    phonemes.push_back(fin);
    phonemes.push_back(tone);

    for (char c : trail_punct)
    {
      std::string p(1, c);
      phonemes.push_back(p);
    }
  }

  if (phonemes.empty()) return {};

  return {phonemes};
}

std::vector<std::vector<std::string>> ChinesePhonemizer::phonemize(const std::string& text)
{
  std::vector<std::string> cur;
  std::vector<std::vector<std::string>> sentences;

  // iterate over utf8 codepoints to get per-char string
  auto view = una::views::utf8(text);
  std::string cur_utf8_char;
  // We need to iterate and build per character utf8 string
  for (auto it = view.begin(); it != view.end(); ++it)
  {
    char32_t cp = *it;
    // Convert cp back to utf8 string
    std::string ch_utf8;
    // encode
    if (cp < 0x80)
      ch_utf8.push_back(static_cast<char>(cp));
    else if (cp < 0x800)
    {
      ch_utf8.push_back(static_cast<char>(0xC0 | (cp >> 6)));
      ch_utf8.push_back(static_cast<char>(0x80 | (cp & 0x3F)));
    }
    else if (cp < 0x10000)
    {
      ch_utf8.push_back(static_cast<char>(0xE0 | (cp >> 12)));
      ch_utf8.push_back(static_cast<char>(0x80 | ((cp >> 6) & 0x3F)));
      ch_utf8.push_back(static_cast<char>(0x80 | (cp & 0x3F)));
    }
    else
    {
      ch_utf8.push_back(static_cast<char>(0xF0 | (cp >> 18)));
      ch_utf8.push_back(static_cast<char>(0x80 | ((cp >> 12) & 0x3F)));
      ch_utf8.push_back(static_cast<char>(0x80 | ((cp >> 6) & 0x3F)));
      ch_utf8.push_back(static_cast<char>(0x80 | (cp & 0x3F)));
    }

    // handle sentence boundary punctuation that triggers new sentence
    if (ch_utf8 == "。" || ch_utf8 == "？" || ch_utf8 == "！" || ch_utf8 == "." || ch_utf8 == "?" || ch_utf8 == "!")
    {
      if (!cur.empty())
      {
        // include punctuation as phoneme before closing sentence
        cur.push_back(ch_utf8);
        sentences.push_back(cur);
        cur.clear();
      }
      else
      {
        // empty sentence with only punctuation still push?
        sentences.push_back({ch_utf8});
      }
      continue;
    }
    if (ch_utf8 == "，") ch_utf8 = ",";
    if (ch_utf8 == "、") ch_utf8 = ",";
    if (ch_utf8 == "：") ch_utf8 = ":";
    if (ch_utf8 == "；") ch_utf8 = ";";

    if (ch_utf8 == "," || ch_utf8 == ":" || ch_utf8 == ";" || ch_utf8 == " " || ch_utf8 == "\n")
    {
      if (ch_utf8 == " " || ch_utf8 == "\n")
      {
        // skip spaces for Hanzi? keep as short pause?
        // include space as phoneme if desired; skip for now
        continue;
      }
      cur.push_back(ch_utf8);
      continue;
    }

    // Phase 1 mono-only: accept only unambiguous one-reading entries.
    // - mono_dict (MONOPHONIC_CHARS.txt) is authoritative mono table
    // - otherwise allow char_bopomofo_dict only if it has exactly one reading
    // - ambiguous (polyphonic) chars are treated as unsupported -> return empty
    //   to avoid silently assigning first sense. This prevents 重庆/银行/长江
    //   from being mis-assigned when only char_bopomofo_dict.json is present.
    // Relaxed: use first reading for poly to avoid empty -> silence.
    std::string bopo;
    auto itm = mono_dict.find(ch_utf8);
    if (itm != mono_dict.end())
    {
      bopo = itm->second;
    }
    else
    {
      auto itc = char_bopomofo_dict.find(ch_utf8);
      if (itc == char_bopomofo_dict.end() || itc->second.empty())
      {
        // unknown char, skip
        continue;
      }
      // relaxed: first reading for polyphonic
      bopo = itc->second[0];
    }

    std::string pinyin = bopomofo_to_pinyin(bopo);
    if (pinyin.empty()) continue;
    auto [ini, fin, tone] = split_initial_final_tone(pinyin);
    if (fin.empty() && tone.empty()) continue;
    if (ini.empty()) ini = "Ø";
    cur.push_back(ini);
    cur.push_back(fin);
    cur.push_back(tone);
  }

  if (!cur.empty()) sentences.push_back(cur);

  if (sentences.empty() && !text.empty())
  {
    // fallback try pinyin direct
    auto alt = phonemize_pinyin_text(text);
    if (!alt.empty()) return alt;
  }

  return sentences;
}

std::vector<int64_t> ChinesePhonemizer::phonemes_to_ids_pinyin(
    const std::vector<std::string>& phonemes, const std::map<std::string, std::vector<int64_t>>& id_map)
{
  return phonemes_to_ids(phonemes, id_map);
}

}  // namespace piper
