#ifndef CHINESE_PHONEMIZER_H_
#define CHINESE_PHONEMIZER_H_

#include <cstdint>
#include <map>
#include <optional>
#include <set>
#include <string>
#include <tuple>
#include <vector>

#if defined(_WIN32) || defined(_WIN64)
#if defined(BUILDING_LIBPIPER)
#define CHINESE_PHONEMIZER_API __declspec(dllexport)
#else
#define CHINESE_PHONEMIZER_API __declspec(dllimport)
#endif
#else
#define CHINESE_PHONEMIZER_API
#endif

namespace piper {

extern CHINESE_PHONEMIZER_API const std::vector<std::string> PINYIN_INITIALS;
extern CHINESE_PHONEMIZER_API const std::set<std::string> GROUP_END_PHONEMES;
extern CHINESE_PHONEMIZER_API const std::set<std::string> PINYIN_PUNCTUATIONS;

CHINESE_PHONEMIZER_API std::string
normalize_g2pw_syllable(const std::string &syl);
CHINESE_PHONEMIZER_API std::tuple<std::string, std::string, std::string>
split_initial_final_tone(const std::string &syl);

CHINESE_PHONEMIZER_API std::optional<char32_t>
get_codepoint_str(const std::string &s);

CHINESE_PHONEMIZER_API std::vector<int64_t>
phonemes_to_ids(const std::vector<std::string> &phonemes,
                const std::map<std::string, std::vector<int64_t>> &id_map);

class CHINESE_PHONEMIZER_API ChinesePhonemizer {
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
  std::map<std::string, std::vector<std::string>> char_bopomofo_dict;
  std::map<std::string, std::string> bopomofo2pinyin;
  bool has_dicts = false;

  std::string bopomofo_to_pinyin(const std::string &bopomofo) const;
};

} // namespace piper

#endif // CHINESE_PHONEMIZER_H_
