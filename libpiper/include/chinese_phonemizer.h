#ifndef CHINESE_PHONEMIZER_H_
#define CHINESE_PHONEMIZER_H_

#include <cstdint>
#include <map>
#include <optional>
#include <set>
#include <string>
#include <tuple>
#include <vector>

namespace piper {

extern const std::vector<std::string> PINYIN_INITIALS;
extern const std::set<std::string> GROUP_END_PHONEMES;
extern const std::set<std::string> PINYIN_PUNCTUATIONS;

std::string normalize_g2pw_syllable(const std::string &syl);
std::tuple<std::string, std::string, std::string>
split_initial_final_tone(const std::string &syl);

std::optional<char32_t> get_codepoint_str(const std::string &s);

std::vector<int64_t>
phonemes_to_ids(const std::vector<std::string> &phonemes,
                const std::map<std::string, std::vector<int64_t>> &id_map);

class ChinesePhonemizer {
public:
  ChinesePhonemizer() = default;

  bool load(const std::string &g2pw_model_dir);

  static std::vector<std::vector<std::string>>
  phonemize_pinyin_text(const std::string &text);

  std::vector<std::vector<std::string>> phonemize(const std::string &text);

  static std::vector<int64_t> phonemes_to_ids_pinyin(
      const std::vector<std::string> &phonemes,
      const std::map<std::string, std::vector<int64_t>> &id_map);

  bool hasDicts() const { return has_dicts; }

private:
  std::map<std::string, std::string> mono_dict; // char utf8 -> bopomofo
  std::map<std::string, std::vector<std::string>> poly_dict;
  std::map<std::string, std::vector<std::string>> char_bopomofo_dict;
  std::map<std::string, std::string> bopomofo2pinyin;
  std::map<std::string, std::string> s2t;
  bool has_dicts = false;

  std::string bopomofo_to_pinyin(const std::string &bopomofo) const;
};

} // namespace piper

#endif // CHINESE_PHONEMIZER_H_
