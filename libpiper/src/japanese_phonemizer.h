#ifndef JAPANESE_PHONEMIZER_H_
#define JAPANESE_PHONEMIZER_H_

#include <cstdint>
#include <mutex>
#include <string>
#include <vector>

// OpenJTalk frontend structs (defined by the openjtalk dependency).
// Forward-declared with the same typedef pattern the real headers use
// (`typedef struct _Mecab { ... } Mecab;`), so this header stays valid both
// with and without the OpenJTalk headers included.
typedef struct _Mecab Mecab;
typedef struct _NJD NJD;
typedef struct _JPCommon JPCommon;

#if defined(_WIN32) || defined(_WIN64)
#if defined(BUILDING_LIBPIPER)
#define JAPANESE_PHONEMIZER_API __declspec(dllexport)
#else
#define JAPANESE_PHONEMIZER_API __declspec(dllimport)
#endif
#else
#define JAPANESE_PHONEMIZER_API
#endif

namespace piper {

// Japanese phonemizer: OpenJTalk full-context labels -> IPA + prosody symbols.
//
// C++ port of piper/phonemize_japanese.py (training-time phonemizer). Output
// must match the Python implementation exactly: the ja_JA voice was trained
// on its output, so any deviation here is a training/inference mismatch.
//
// Pipeline per sentence (mirrors pyopenjtalk-plus, which is what the `ja`
// training extra installs):
//   text2mecab -> Mecab_analysis -> mecab2njd -> njd_set_pronunciation ->
//   apply_original_rule_before_chaining (accent chaining fixes ported from
//   pyopenjtalk's Python) -> njd_set_digit -> njd_set_accent_phrase ->
//   njd_set_accent_type -> njd_set_unvoiced_vowel -> njd_set_long_vowel ->
//   njd2jpcommon -> JPCommon_make_label
// Labels are then parsed into OpenJTalk phones plus prosody symbols
// (accent rise ↑, accent fall ↓, accent phrase boundary #, pause ,, sentence
// end ./ ?), and mapped to IPA with OPENJTALK_TO_IPA.
//
// NOTE: marine neural accent estimation is intentionally out of scope, matching
// the default (non-marine) Python path used for training.
//
// The OpenJTalk structs are not thread-safe; all public methods take an
// internal lock (same as pyopenjtalk's per-instance lock).
class JAPANESE_PHONEMIZER_API JapanesePhonemizer {
public:
  JapanesePhonemizer();
  ~JapanesePhonemizer();

  JapanesePhonemizer(const JapanesePhonemizer &) = delete;
  JapanesePhonemizer &operator=(const JapanesePhonemizer &) = delete;

  // Load the OpenJTalk system dictionary directory (contains sys.dic,
  // matrix.bin, char.bin, unk.dic). Returns false on failure.
  // The pyopenjtalk-plus dictionary (mecab-naist-jdic base + jpreprocess
  // fixes) is required for training parity; stock open_jtalk_dic_utf_8-1.11
  // gives different readings on some words.
  bool load(const std::string &openjtalk_dict_dir);

  bool isLoaded() const { return loaded_; }

  // Phonemize text into one UTF-8 string per sentence. Each string is the
  // concatenation of single-codepoint phonemes (IPA + prosody symbols ↑↓#,./?),
  // ready for the shared phoneme->id tail in piper_synthesize_start.
  // Returns an empty vector when the dictionary is not loaded.
  // Never throws: internal errors are swallowed and yield no sentences,
  // mirroring the Python implementation's per-sentence try/except.
  std::vector<std::string> phonemize(const std::string &text);

  // Split text into sentences, keeping final punctuation.
  // Exposed for testing (mirrors _split_sentences in the Python module).
  static std::vector<std::string> splitSentences(const std::string &text);

private:
  std::string phonemizeSentence(const std::string &sentence);

  bool loaded_ = false;
  bool drop_devoiced_vowels_ = true;

  Mecab *mecab_ = nullptr;
  NJD *njd_ = nullptr;
  JPCommon *jpcommon_ = nullptr;

  mutable std::mutex mutex_;
};

} // namespace piper

#endif // JAPANESE_PHONEMIZER_H_
