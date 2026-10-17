// Japanese phonemizer: OpenJTalk full-context labels -> IPA + prosody symbols.
//
// C++ port of src/piper/phonemize_japanese.py from piper1-gpl 1.7.0.
// The ja_JA voice was trained on the Python implementation's output, so this
// file must stay behavior-identical to it. When in doubt, match the Python.

#include "japanese_phonemizer.h"

// OpenJTalk frontend (built via ExternalProject from tsukumijima/open_jtalk,
// the same fork pyopenjtalk-plus vendors).
#include "jpcommon.h"
#include "mecab.h"
#include "mecab2njd.h"
#include "njd.h"
#include "njd2jpcommon.h"
#include "njd_set_accent_phrase.h"
#include "njd_set_accent_type.h"
#include "njd_set_digit.h"
#include "njd_set_long_vowel.h"
#include "njd_set_pronunciation.h"
#include "njd_set_unvoiced_vowel.h"
#include "text2mecab.h"

#include <cstring>
#include <regex>
#include <unordered_map>
#include <unordered_set>

namespace piper {
namespace {

// Must match pyopenjtalk's TEXT2MECAB_BUFFER_SIZE (16384).
constexpr size_t TEXT2MECAB_BUF_SIZE = 16384;

// "no match" sentinel for numeric label fields, matching ESPnet's choice.
constexpr int NO_FEATURE = -50;

// OpenJTalk phone -> IPA. Palatalized consonants uniformly use ʲ rather than
// their closest single-symbol equivalents (ny -> nʲ, not ɲ) to keep the series
// consistent. Long vowels stay as two identical vowels because Japanese counts
// them as two morae, and mora timing is what the duration predictor should see.
const std::unordered_map<std::string, std::string> &openjtalkToIpa() {
  static const auto *map = new std::unordered_map<std::string, std::string>{
      // Vowels
      {"a", "a"},
      {"i", "i"},
      {"u", "ɯ"}, // compressed close back unrounded, not [u]
      {"e", "e"},
      {"o", "o"},
      // Consonants
      {"k", "k"},
      {"ky", "kʲ"}, // キャ
      {"kw", "kʷ"}, // クヮ
      {"g", "ɡ"},
      {"gy", "ɡʲ"}, // ギャ
      {"gw", "ɡʷ"}, // グヮ
      {"s", "s"},
      {"sh", "ɕ"}, // シ
      {"z", "z"},
      {"j", "dʑ"}, // ジャ
      {"t", "t"},
      {"ts", "ts"}, // ツ
      {"ty", "tʲ"}, // テャ
      {"ch", "tɕ"}, // チ
      {"d", "d"},
      {"dy", "dʲ"}, // デャ
      {"n", "n"},
      {"ny", "nʲ"}, // ニャ
      {"h", "h"},
      {"hy", "hʲ"}, // ヒャ
      {"f", "ɸ"},   // フ
      {"b", "b"},
      {"by", "bʲ"}, // ビャ
      {"p", "p"},
      {"py", "pʲ"}, // ピャ
      {"m", "m"},
      {"my", "mʲ"}, // ミャ
      {"y", "j"},   // ヤ
      {"r", "ɾ"},
      {"ry", "ɾʲ"}, // リャ
      {"w", "w"},
      {"v", "v"}, // ヴ
      // Specials
      {"N", "ɴ"},  // ん (moraic nasal)
      {"cl", "ʔ"}, // っ (geminate closure)
  };
  return *map;
}

// OpenJTalk marks devoiced vowels with an uppercase letter (desU = です).
bool isDevoicedVowel(const std::string &phone) {
  return (phone.size() == 1) &&
         (phone[0] == 'A' || phone[0] == 'I' || phone[0] == 'U' ||
          phone[0] == 'E' || phone[0] == 'O');
}

// Vowels and moraic phones that can carry an accent phrase boundary.
bool isMoraFinalPhone(const std::string &phone) {
  static const std::unordered_set<std::string> kMoraFinal = {
      "a", "i", "u", "e", "o", "A", "I", "U", "E", "O", "N", "cl"};
  return kMoraFinal.count(phone) != 0;
}

// Prosody symbols. Chosen so they already have ids in the default phoneme id
// map (see the Python module docstring for why _ and $ are avoided).
constexpr char32_t ACCENT_RISE = 0x2191;          // ↑ low -> high
constexpr char32_t ACCENT_FALL = 0x2193;          // ↓ accent nucleus
constexpr char32_t ACCENT_PHRASE_BOUNDARY = U'#'; // #
constexpr char32_t PAUSE = U',';                  // , (OpenJTalk pau, e.g. 、)
constexpr char32_t DECLARATIVE_END = U'.';        // .
constexpr char32_t INTERROGATIVE_END = U'?';      // ?

// --- UTF-8 helpers (minimal, dependency-free) ---

// Decode one codepoint. Returns bytes consumed, or 0 on invalid input.
size_t decodeUtf8(const char *s, size_t len, char32_t *out) {
  if (len == 0)
    return 0;
  auto c = static_cast<unsigned char>(s[0]);
  if (c < 0x80) {
    *out = c;
    return 1;
  }
  size_t want = 0;
  char32_t cp = 0;
  if ((c & 0xE0) == 0xC0) {
    want = 2;
    cp = c & 0x1F;
  } else if ((c & 0xF0) == 0xE0) {
    want = 3;
    cp = c & 0x0F;
  } else if ((c & 0xF8) == 0xF0) {
    want = 4;
    cp = c & 0x07;
  } else {
    return 0;
  }
  if (len < want)
    return 0;
  for (size_t i = 1; i < want; i++) {
    auto d = static_cast<unsigned char>(s[i]);
    if ((d & 0xC0) != 0x80)
      return 0;
    cp = (cp << 6) | (d & 0x3F);
  }
  *out = cp;
  return want;
}

void appendUtf8(std::string &out, char32_t cp) {
  if (cp < 0x80) {
    out.push_back(static_cast<char>(cp));
  } else if (cp < 0x800) {
    out.push_back(static_cast<char>(0xC0 | (cp >> 6)));
    out.push_back(static_cast<char>(0x80 | (cp & 0x3F)));
  } else if (cp < 0x10000) {
    out.push_back(static_cast<char>(0xE0 | (cp >> 12)));
    out.push_back(static_cast<char>(0x80 | ((cp >> 6) & 0x3F)));
    out.push_back(static_cast<char>(0x80 | (cp & 0x3F)));
  } else {
    out.push_back(static_cast<char>(0xF0 | (cp >> 18)));
    out.push_back(static_cast<char>(0x80 | ((cp >> 12) & 0x3F)));
    out.push_back(static_cast<char>(0x80 | ((cp >> 6) & 0x3F)));
    out.push_back(static_cast<char>(0x80 | (cp & 0x3F)));
  }
}

// Iterate codepoints with byte offsets.
struct Codepoint {
  char32_t cp;
  size_t byte_offset;
  size_t byte_len;
};

std::vector<Codepoint> toCodepoints(const std::string &s) {
  std::vector<Codepoint> out;
  size_t i = 0;
  while (i < s.size()) {
    char32_t cp = 0;
    size_t n = decodeUtf8(s.data() + i, s.size() - i, &cp);
    if (n == 0) { // invalid byte: skip like Python's replacement would not;
                  // keep alignment by consuming one byte
      n = 1;
      cp = 0xFFFD;
    }
    out.push_back({cp, i, n});
    i += n;
  }
  return out;
}

// Python str.isspace() covers these plus ASCII whitespace.
bool isUnicodeSpace(char32_t cp) {
  if (cp < 0x80)
    return std::isspace(static_cast<int>(cp)) != 0;
  switch (cp) {
  case 0x00A0: // NO-BREAK SPACE
  case 0x1680: // OGHAM SPACE MARK
  case 0x2000: // EN QUAD
  case 0x2001: // EM QUAD
  case 0x2002: // EN SPACE
  case 0x2003: // EM SPACE
  case 0x2004: // THREE-PER-EM SPACE
  case 0x2005: // FOUR-PER-EM SPACE
  case 0x2006: // SIX-PER-EM SPACE
  case 0x2007: // FIGURE SPACE
  case 0x2008: // PUNCTUATION SPACE
  case 0x2009: // THIN SPACE
  case 0x200A: // HAIR SPACE
  case 0x2028: // LINE SEPARATOR
  case 0x2029: // PARAGRAPH SEPARATOR
  case 0x202F: // NARROW NO-BREAK SPACE
  case 0x205F: // MEDIUM MATHEMATICAL SPACE
  case 0x3000: // IDEOGRAPHIC SPACE
    return true;
  default:
    return false;
  }
}

// Python str.isdigit() on the chars before/after "." (covers full-width
// digits).
bool isUnicodeDigit(char32_t cp) {
  return (cp >= U'0' && cp <= U'9') || (cp >= 0xFF10 && cp <= 0xFF19);
}

bool strEq(const char *a, const char *b) {
  if (a == nullptr || b == nullptr)
    return a == b;
  return std::strcmp(a, b) == 0;
}

bool strEndsWith(const char *s, const char *suffix) {
  if (s == nullptr || suffix == nullptr)
    return false;
  size_t sl = std::strlen(s), xl = std::strlen(suffix);
  return (sl >= xl) && (std::strcmp(s + sl - xl, suffix) == 0);
}

// Python's str[:-n] slices codepoints, not bytes.
std::string dropLastCodepoints(const char *s, size_t n) {
  if (s == nullptr)
    return {};
  std::string str(s);
  auto cps = toCodepoints(str);
  if (cps.size() <= n)
    return {};
  return str.substr(0, cps[cps.size() - n].byte_offset);
}

bool hasCodepointInRange(const char *s, char32_t lo, char32_t hi) {
  if (s == nullptr)
    return false;
  for (const auto &cp : toCodepoints(s)) {
    if (cp.cp >= lo && cp.cp <= hi)
      return true;
  }
  return false;
}

bool strIn(const char *s, std::initializer_list<const char *> options) {
  for (const char *o : options) {
    if (strEq(s, o))
      return true;
  }
  return false;
}

// Port of pyopenjtalk's apply_original_rule_before_chaining (accent chaining
// fixes applied between njd_set_pronunciation and njd_set_digit). Operates
// directly on the NJD linked list instead of round-tripping through Python
// feature dicts.
void applyChainingRules(NJD *njd) {
  for (NJDNode *node = njd->head; node != nullptr && node->next != nullptr;
       node = node->next) {
    NJDNode *prev = node->prev;
    NJDNode *next = node->next;
    NJDNode *following = next->next;

    // 名詞の後ろで新しい語を作る「不足」は連濁したブソクと読む
    if (strEq(node->pos, "名詞") && strEq(next->string, "不足") &&
        strEq(next->pron, "フソク")) {
      NJDNode_set_read(next, "ブソク");
      NJDNode_set_pron(next, "ブソク");
    }

    // 分母を表す「数値 + 分 + の + 数値」はブンと読む
    bool is_fraction_denominator = false;
    if (following != nullptr && strEq(next->string, "の")) {
      is_fraction_denominator = strEq(following->pos_group1, "数");
    }
    if (is_fraction_denominator && strEndsWith(node->string, "分")) {
      if (strEndsWith(node->pron, "フン") || strEndsWith(node->pron, "プン")) {
        std::string read = dropLastCodepoints(node->read, 2) + "ブン";
        std::string pron = dropLastCodepoints(node->pron, 2) + "ブン";
        NJDNode_set_read(node, read.c_str());
        NJDNode_set_pron(node, pron.c_str());
      } else if (strEndsWith(node->pron, "ブ")) {
        std::string read = std::string(node->read ? node->read : "") + "ン";
        std::string pron = std::string(node->pron ? node->pron : "") + "ン";
        NJDNode_set_read(node, read.c_str());
        NJDNode_set_pron(node, pron.c_str());
      }
    }

    // 算用数字が別形態素になった分数では、数詞と「の」に挟まれた助数詞の分をブンへ変える
    if (prev != nullptr && following != nullptr && strEq(node->string, "分") &&
        strEq(prev->pos_group1, "数") && strEq(next->string, "の") &&
        strEq(following->pos_group1, "数")) {
      NJDNode_set_read(node, "ブン");
      NJDNode_set_pron(node, "ブン");
    }

    // 2文字以上連続する「〇」は伏字なのでマルと読む
    if (strEq(node->string, "〇") && strEq(next->string, "〇")) {
      for (NJDNode *p : {node, next}) {
        NJDNode_set_pos_group1(p, "一般");
        NJDNode_set_read(p, "マル");
        NJDNode_set_pron(p, "マル");
        NJDNode_set_acc(p, 1);
        NJDNode_set_mora_size(p, 2);
      }
    }

    // 接尾辞「球」は漢語・外来語との生産的な結合をキュウとし、送り仮名を持つ和語だけ連濁させる
    if (strEq(next->string, "球") && strEq(next->pos, "名詞") &&
        strEq(next->pos_group1, "接尾") && strEq(next->pron, "キュー") &&
        hasCodepointInRange(node->string, 0x4E00, 0x9FFF) && // 一..鿿
        hasCodepointInRange(node->string, 0x3041, 0x3096)) { // ぁ..ゖ
      NJDNode_set_read(next, "ダマ");
      NJDNode_set_pron(next, "ダマ");
      NJDNode_set_acc(next, 1);
      NJDNode_set_mora_size(next, 2);
      NJDNode_set_chain_rule(next, "C4");
    }

    // サ変動詞(スル)の前にサ変接続や名詞が来た場合は、一つのアクセント句に纏める
    if ((strIn(node->pos_group1, {"サ変接続", "格助詞", "接続助詞"}) ||
         (strEq(node->pos, "名詞") && strEq(node->pos_group1, "一般")) ||
         strEq(node->pos, "副詞")) &&
        strEq(next->ctype, "サ変・スル")) {
      NJDNode_set_chain_flag(next, 1);
    }

    // ご遠慮、ご配慮のような接頭語がつく場合にその後に続く単語の結合則を変更する
    if (strIn(node->string, {"お", "御", "ご"}) &&
        strEq(node->chain_rule, "P1")) {
      if (next->acc == 0 || next->acc == next->mora_size) {
        NJDNode_set_chain_rule(next, "C4");
        NJDNode_set_acc(next, 0);
      } else {
        NJDNode_set_chain_rule(next, "C1");
      }
    }

    // 動詞(自立)が連続する場合、後ろの動詞のアクセント核が採用される
    if (strEq(node->pos, "動詞") && strEq(next->pos, "動詞")) {
      NJDNode_set_chain_rule(next, next->acc != 0 ? "C1" : "C4");
    }

    // 連用形のアクセント核の登録を修正する
    if (strIn(node->cform,
              {"連用形", "連用タ接続", "連用ゴザイ接続", "連用テ接続"}) &&
        node->acc == node->mora_size && node->mora_size > 1) {
      NJDNode_set_acc(node, node->acc - 1);
    }

    // 「らる、られる」＋「た」の組み合わせで「た」の助動詞/F2@0を上書きしてアクセントを下げないようにする
    if (strIn(node->orig, {"れる", "られる", "せる", "させる", "ちゃう"}) &&
        strEq(next->string, "た")) {
      NJDNode_set_chain_rule(next, "F2@1");
    }

    // 形容詞＋「なる、する」は一つのアクセント句に纏める
    if (strEq(node->pos, "形容詞") && strIn(next->orig, {"なる", "する"})) {
      NJDNode_set_chain_flag(next, 1);
    }
  }
}

// --- pyopenjtalk-plus module-level post-processing ---
//
// Port of pyopenjtalk/__init__.py::apply_postprocessing(), which piper's
// phonemize_japanese.py reaches via the module-level run_frontend(). These run
// on the NJD nodes AFTER njd_set_long_vowel() and BEFORE njd2jpcommon(),
// matching the training-time pipeline.
//
// Deliberately NOT ported:
// - predict_nani_reading(): needs the ONNX nani model. The base
//   pyopenjtalk-plus install (what piper's `ja` extra pulls) does not include
//   onnxruntime, so this step is a no-op wherever onnxruntime is absent.
// - modify_kanji_yomi(): needs Sudachi; there is no C++ equivalent available.
// - process_odori_features(): 踊り字/一の字点 handling, partly requiring MeCab
//   re-analysis. TODO for a follow-up.

// _DAN_MAP from pyopenjtalk/utils.py: katakana -> vowel row
// ('a'/'i'/'u'/'e'/'o'). Used to detect unnatural long-vowel-ization of the
// auxiliary "う".
char kanaDanRow(const std::string &kana) {
  static const std::pair<const char *, char> kMap[] = {
      {"ア", 'a'}, {"カ", 'a'}, {"サ", 'a'}, {"タ", 'a'}, {"ナ", 'a'},
      {"ハ", 'a'}, {"マ", 'a'}, {"ヤ", 'a'}, {"ラ", 'a'}, {"ワ", 'a'},
      {"ガ", 'a'}, {"ザ", 'a'}, {"ダ", 'a'}, {"バ", 'a'}, {"パ", 'a'},
      {"ァ", 'a'}, {"イ", 'i'}, {"キ", 'i'}, {"シ", 'i'}, {"チ", 'i'},
      {"ニ", 'i'}, {"ヒ", 'i'}, {"ミ", 'i'}, {"リ", 'i'}, {"ギ", 'i'},
      {"ジ", 'i'}, {"ヂ", 'i'}, {"ビ", 'i'}, {"ピ", 'i'}, {"ィ", 'i'},
      {"ウ", 'u'}, {"ク", 'u'}, {"ス", 'u'}, {"ツ", 'u'}, {"ヌ", 'u'},
      {"フ", 'u'}, {"ム", 'u'}, {"ユ", 'u'}, {"ル", 'u'}, {"グ", 'u'},
      {"ズ", 'u'}, {"ヅ", 'u'}, {"ブ", 'u'}, {"プ", 'u'}, {"ヴ", 'u'},
      {"ゥ", 'u'}, {"エ", 'e'}, {"ケ", 'e'}, {"セ", 'e'}, {"テ", 'e'},
      {"ネ", 'e'}, {"ヘ", 'e'}, {"メ", 'e'}, {"レ", 'e'}, {"ゲ", 'e'},
      {"ゼ", 'e'}, {"デ", 'e'}, {"ベ", 'e'}, {"ペ", 'e'}, {"ェ", 'e'},
      {"オ", 'o'}, {"コ", 'o'}, {"ソ", 'o'}, {"ト", 'o'}, {"ノ", 'o'},
      {"ホ", 'o'}, {"モ", 'o'}, {"ヨ", 'o'}, {"ロ", 'o'}, {"ヲ", 'o'},
      {"ゴ", 'o'}, {"ゾ", 'o'}, {"ド", 'o'}, {"ボ", 'o'}, {"ポ", 'o'},
      {"ォ", 'o'},
  };
  for (const auto &e : kMap) {
    if (kana == e.first)
      return e.second;
  }
  return 0;
}

// Port of modify_filler_accent(): keep a filler from dragging the following
// noun into its accent phrase.
void modifyFillerAccent(NJD *njd) {
  bool is_after_filler = false;
  for (NJDNode *node = njd->head; node != nullptr; node = node->next) {
    if (strEq(node->pos, "フィラー")) {
      if (node->acc > node->mora_size)
        NJDNode_set_acc(node, 0);
      is_after_filler = true;
    } else if (is_after_filler) {
      if (strEq(node->pos, "名詞"))
        NJDNode_set_chain_flag(node, 0);
      is_after_filler = false;
    }
  }
}

// Port of suppress_unnatural_auxiliary_u_long_vowel(): undo NJD's unconditional
// long-vowel-ization of the auxiliary "う" after a/i/e-row verb stems.
void suppressUnnaturalAuxiliaryULongVowel(NJD *njd) {
  for (NJDNode *node = njd->head; node != nullptr && node->next != nullptr;
       node = node->next) {
    NJDNode *next = node->next;
    if (!strEq(next->pron, "ー") || !strEq(next->read, "ウ"))
      continue;
    // current_pron = node.pron with trailing "’" (unvoiced-vowel mark) removed.
    std::string current_pron = node->pron ? node->pron : "";
    while (strEndsWith(current_pron.c_str(), "’"))
      current_pron = dropLastCodepoints(current_pron.c_str(), 1);
    if (current_pron.empty())
      continue;
    auto cps = toCodepoints(current_pron);
    std::string last;
    appendUtf8(last, cps.back().cp);
    char row = kanaDanRow(last);
    if (row == 'a' || row == 'i' || row == 'e')
      NJDNode_set_pron(next, "ウ");
  }
}

// Port of retreat_acc_nuc(): if the accent nucleus lands on a long vowel,
// geminate or moraic nasal, retreat it one mora.
void retreatAccNuc(NJD *njd) {
  if (njd->head == nullptr)
    return;
  static const char *kBadNucleus[] = {"ー", "ッ", "ン"};
  static const char32_t kYouon[] = {0x30E3, 0x30E5, 0x30E7, 0x30A1, 0x30A3,
                                    0x30A5, 0x30A7, 0x30A9}; // ャュョァィゥェォ
  int acc = 0;
  NJDNode *head = njd->head;
  for (NJDNode *node = njd->head; node != nullptr; node = node->next) {
    // The node right after an accent boundary (chain_flag 0 or -1) carries the
    // nucleus position for the phrase.
    if (node->chain_flag == 0 || node->chain_flag == -1) {
      head = node;
      acc = node->acc;
    }
    // pron with youon (small kana) removed, for nucleus indexing.
    std::string pron = node->pron ? node->pron : "";
    std::string stripped;
    for (const auto &c : toCodepoints(pron)) {
      bool youon = false;
      for (char32_t y : kYouon) {
        if (c.cp == y) {
          youon = true;
          break;
        }
      }
      if (!youon)
        appendUtf8(stripped, c.cp);
    }
    if (stripped.empty())
      stripped = pron;
    auto stripped_cps = toCodepoints(stripped);

    if (acc > 0) {
      if (acc <= node->mora_size) {
        std::string nuc;
        if (static_cast<size_t>(acc - 1) < stripped_cps.size())
          appendUtf8(nuc, stripped_cps[static_cast<size_t>(acc - 1)].cp);
        else if (!stripped_cps.empty())
          appendUtf8(nuc, stripped_cps[0].cp);
        for (const char *bad : kBadNucleus) {
          if (nuc == bad) {
            NJDNode_set_acc(head, head->acc - 1);
            break;
          }
        }
        acc = -1;
      } else {
        acc = acc - node->mora_size;
      }
    }
  }
}

// Port of modify_acc_after_chaining(): the 特殊・マス / 特殊・ナイ /
// れる・られる・すぎる・せる・させる auxiliaries pull the accent nucleus onto
// themselves (書きます → か[きま]す).
void modifyAccAfterChaining(NJD *njd) {
  if (njd->head == nullptr)
    return;
  int acc = 0;
  bool is_after_nuc = false;
  int phase_len = 0;
  NJDNode *head = njd->head;
  for (NJDNode *node = njd->head; node != nullptr; node = node->next) {
    if (node->chain_flag == 0 || node->chain_flag == -1) {
      is_after_nuc = false;
      head = node;
      acc = node->acc;
      phase_len = 0;
    }
    // acc == 0 phrases contain no 特殊・マス to adjust.
    if (acc == 0) {
      continue;
    } else if (is_after_nuc) {
      if (strEq(node->ctype, "特殊・マス")) {
        NJDNode_set_acc(head, strEq(node->cform, "未然形") ? phase_len + 2
                                                           : phase_len + 1);
      } else if (strEq(node->ctype, "特殊・ナイ")) {
        NJDNode_set_acc(head, phase_len);
      } else if (strIn(node->orig,
                       {"れる", "られる", "すぎる", "せる", "させる"})) {
        NJDNode_set_acc(head, phase_len + node->acc);
      } else {
        is_after_nuc = false;
        acc = 0;
      }
      phase_len += node->mora_size;
    } else {
      phase_len += node->mora_size;
      if (acc <= node->mora_size) {
        is_after_nuc = true;
      } else {
        acc = acc - node->mora_size;
      }
    }
  }
}

void applyPostProcessing(NJD *njd) {
  modifyFillerAccent(njd);
  // predict_nani_reading(): skipped (needs the ONNX nani model).
  // modify_kanji_yomi(): skipped (needs Sudachi).
  suppressUnnaturalAuxiliaryULongVowel(njd);
  retreatAccNuc(njd);
  modifyAccAfterChaining(njd);
  // process_odori_features(): TODO (needs MeCab re-analysis for some cases).
}

// --- Label parsing ---

int numericFeature(const std::string &label, const std::regex &pattern) {
  std::smatch m;
  if (!std::regex_search(label, m, pattern))
    return NO_FEATURE;
  try {
    return std::stoi(m[1].str());
  } catch (...) {
    // Unset fields are written "xx"
    return NO_FEATURE;
  }
}

// Port of JapanesePhonemizer._phonemize_sentence: parse one sentence's
// full-context labels into OpenJTalk phones + prosody symbols.
std::vector<std::string> phonemizeSentenceLabels(char **labels, int num_labels,
                                                 bool drop_devoiced) {
  static const std::regex kPhoneRe(R"(\-(.*?)\+)");
  static const std::regex kQuestionRe(R"(!(\d+)_)");

  std::vector<std::string> phones;

  for (int i = 0; i < num_labels; i++) {
    const std::string label(labels[i] ? labels[i] : "");
    std::smatch m;
    if (!std::regex_search(label, m, kPhoneRe))
      continue;

    std::string phone = m[1].str();
    if (drop_devoiced && isDevoicedVowel(phone)) {
      phone[0] = static_cast<char>(phone[0] - 'A' + 'a');
    }

    if (phone == "sil") {
      // Utterance boundary. The leading one needs no symbol (Piper prepends
      // BOS itself); the trailing one carries the intonation.
      if (i == num_labels - 1) {
        // E:<f1>_<f2>!<e3>_... where e3 == 1 marks a question.
        bool is_question = numericFeature(label, kQuestionRe) == 1;
        phones.push_back(is_question ? "?" : ".");
      }
      continue;
    }

    if (phone == "pau") {
      phones.push_back(",");
      continue;
    }

    phones.push_back(phone);

    if (i >= num_labels - 1) {
      // No following label to compare accent position against.
      continue;
    }

    const std::string next_label(labels[i + 1] ? labels[i + 1] : "");

    // A: mora position within the accent phrase, relative to the accent
    // nucleus. a1 == 0 means this mora *is* the nucleus.
    static const std::regex kA1Re(R"(/A:([0-9\-]+)\+)");
    static const std::regex kA2Re(R"(\+(\d+)\+)");
    static const std::regex kA3Re(R"(\+(\d+)/)");
    // F: number of morae in the current accent phrase.
    static const std::regex kF1Re(R"(/F:(\d+)_)");

    int a1 = numericFeature(label, kA1Re);
    int a2 = numericFeature(label, kA2Re);
    int a3 = numericFeature(label, kA3Re);
    int f1 = numericFeature(label, kF1Re);
    int a2_next = numericFeature(next_label, kA2Re);

    if ((a3 == 1) && (a2_next == 1) && isMoraFinalPhone(phone)) {
      // Last mora of this accent phrase, first mora of the next.
      phones.push_back("#");
    } else if ((a1 == 0) && (a2_next == a2 + 1) && (a2 != f1)) {
      // Accent nucleus, and the phrase continues: pitch falls after.
      phones.push_back("↓");
    } else if ((a2 == 1) && (a2_next == 2)) {
      // Mora 1 -> 2 of an accent phrase: pitch rises.
      phones.push_back("↑");
    }
  }

  return phones;
}

} // namespace

JapanesePhonemizer::JapanesePhonemizer()
    : mecab_(new Mecab()), njd_(new NJD()), jpcommon_(new JPCommon()) {
  Mecab_initialize(mecab_);
  NJD_initialize(njd_);
  JPCommon_initialize(jpcommon_);
}

JapanesePhonemizer::~JapanesePhonemizer() {
  if (mecab_ != nullptr) {
    Mecab_clear(mecab_);
    delete mecab_;
  }
  if (njd_ != nullptr) {
    NJD_clear(njd_);
    delete njd_;
  }
  if (jpcommon_ != nullptr) {
    JPCommon_clear(jpcommon_);
    delete jpcommon_;
  }
}

bool JapanesePhonemizer::load(const std::string &openjtalk_dict_dir) {
  std::lock_guard<std::mutex> lock(mutex_);
  if (Mecab_load(mecab_, openjtalk_dict_dir.c_str()) != 1)
    return false;
  loaded_ = true;
  return true;
}

std::vector<std::string>
JapanesePhonemizer::phonemize(const std::string &text) {
  std::lock_guard<std::mutex> lock(mutex_);
  std::vector<std::string> result;
  if (!loaded_)
    return result;

  for (const auto &sentence : splitSentences(text)) {
    std::string phones = phonemizeSentence(sentence);
    if (!phones.empty())
      result.push_back(std::move(phones));
  }
  return result;
}

std::string JapanesePhonemizer::phonemizeSentence(const std::string &sentence) {
  // Caller holds the lock.
  std::string out;

  char buf[TEXT2MECAB_BUF_SIZE];
  if (text2mecab(buf, sizeof(buf), sentence.c_str()) != 0)
    return out;

  if (Mecab_analysis(mecab_, buf) != 1)
    return out;

  int morph_size = Mecab_get_size(mecab_);
  char **morphs = Mecab_get_feature(mecab_);
  if (morph_size < 0 || (morph_size > 0 && morphs == nullptr)) {
    Mecab_refresh(mecab_);
    return out;
  }

  // pyopenjtalk-plus filters "記号,空白" morphs: text2mecab turns half-width
  // spaces into full-width ones, which MeCab tokenizes as 記号,空白, and
  // feeding those to NJD would insert a spurious pau.
  std::vector<char *> filtered;
  filtered.reserve(static_cast<size_t>(morph_size));
  for (int i = 0; i < morph_size; i++) {
    if (morphs[i] == nullptr)
      continue;
    if (std::strstr(morphs[i], "記号,空白") != nullptr)
      continue;
    filtered.push_back(morphs[i]);
  }

  // Frontend. Exceptions from OpenJTalk C code are not expected, but a refresh
  // guard keeps the shared structs clean for the next sentence either way.
  struct RefreshGuard {
    Mecab *m;
    NJD *n;
    JPCommon *j;
    ~RefreshGuard() {
      Mecab_refresh(m);
      NJD_refresh(n);
      JPCommon_refresh(j);
    }
  } guard{mecab_, njd_, jpcommon_};

  mecab2njd(njd_, filtered.data(), static_cast<int>(filtered.size()));
  njd_set_pronunciation(njd_);
  applyChainingRules(njd_);
  njd_set_digit(njd_);
  njd_set_accent_phrase(njd_);
  njd_set_accent_type(njd_);
  njd_set_unvoiced_vowel(njd_);
  njd_set_long_vowel(njd_);
  applyPostProcessing(njd_);

  njd2jpcommon(jpcommon_, njd_);
  JPCommon_make_label(jpcommon_);

  int label_size = JPCommon_get_label_size(jpcommon_);
  char **label_feature = JPCommon_get_label_feature(jpcommon_);
  if (label_size <= 0 || label_feature == nullptr)
    return out;

  auto phones =
      phonemizeSentenceLabels(label_feature, label_size, drop_devoiced_vowels_);

  // Map to IPA. Multi-symbol IPA (kʲ, tɕ, dʑ, ...) becomes separate
  // single-codepoint phonemes, matching the Python `ipa_phonemes.extend(ipa)`.
  const auto &ipa_map = openjtalkToIpa();
  for (const auto &phone : phones) {
    if (phone == "↑") {
      appendUtf8(out, ACCENT_RISE);
      continue;
    }
    if (phone == "↓") {
      appendUtf8(out, ACCENT_FALL);
      continue;
    }
    if (phone == "#") {
      appendUtf8(out, ACCENT_PHRASE_BOUNDARY);
      continue;
    }
    if (phone == ",") {
      appendUtf8(out, PAUSE);
      continue;
    }
    if (phone == ".") {
      appendUtf8(out, DECLARATIVE_END);
      continue;
    }
    if (phone == "?") {
      appendUtf8(out, INTERROGATIVE_END);
      continue;
    }
    auto it = ipa_map.find(phone);
    if (it == ipa_map.end()) {
      // Python logs a warning and skips.
      continue;
    }
    for (const auto &cp : toCodepoints(it->second)) {
      appendUtf8(out, cp.cp);
    }
  }

  return out;
}

// Sentence-final punctuation, taking any trailing closing brackets/quotes and
// whitespace with it. OpenJTalk itself only turns these into a `pau`, so we
// split first to get one audio chunk per sentence.
// Mirrors _SENTENCE_END_PATTERN = [。．！？!?]+[」』）】〉》”’\"')\]\s]*
std::vector<std::string>
JapanesePhonemizer::splitSentences(const std::string &text) {
  static const std::unordered_set<char32_t> kEnders = {
      0x3002, // 。
      0xFF0E, // ．
      0xFF01, // ！
      0xFF1F, // ？
      U'!',   U'?',
  };
  // Trailing closers/quotes: 」』）】〉》”’"'() ] plus whitespace.
  auto isCloser = [](char32_t cp) {
    switch (cp) {
    case 0x300D: // 」
    case 0x300F: // 』
    case 0xFF09: // ）
    case 0x3011: // 】
    case 0x3009: // 〉
    case 0x300B: // 》
    case 0x201D: // ”
    case 0x2019: // ’
    case U'"':
    case U'\'':
    case U')':
    case U']':
      return true;
    default:
      break;
    }
    // \s: use the Unicode-aware helper (ASCII whitespace + U+3000 + friends).
    return isUnicodeSpace(cp);
  };
  auto trim = [](const std::string &s) {
    auto cps = toCodepoints(s);
    size_t b0 = 0, b1 = s.size();
    size_t i = 0;
    while (i < cps.size() && isUnicodeSpace(cps[i].cp)) {
      b0 = cps[i].byte_offset + cps[i].byte_len;
      i++;
    }
    size_t j = cps.size();
    while (j > i && isUnicodeSpace(cps[j - 1].cp)) {
      b1 = cps[j - 1].byte_offset;
      j--;
    }
    return s.substr(b0, b1 - b0);
  };

  std::vector<std::string> sentences;
  auto cps = toCodepoints(text);
  size_t start_byte = 0;

  for (size_t i = 0; i < cps.size(); i++) {
    if (kEnders.count(cps[i].cp) == 0)
      continue;

    // Consume trailing closers/quotes/whitespace.
    size_t j = i + 1;
    while (j < cps.size() && isCloser(cps[j].cp))
      j++;

    // Decimal guard: the "." in "1.5" is not a sentence boundary.
    bool consumed_trailer = (j > i + 1);
    if (!consumed_trailer && cps[i].cp == U'.') {
      bool before_digit = (i > 0) && isUnicodeDigit(cps[i - 1].cp);
      bool after_digit = (j < cps.size()) && isUnicodeDigit(cps[j].cp);
      if (before_digit && after_digit)
        continue;
    }

    size_t end_byte = (j < cps.size())
                          ? cps[j].byte_offset
                          : cps.back().byte_offset + cps.back().byte_len;
    std::string sentence = trim(text.substr(start_byte, end_byte - start_byte));
    if (!sentence.empty())
      sentences.push_back(std::move(sentence));
    start_byte = end_byte;
    i = j - 1;
  }

  std::string tail = trim(text.substr(start_byte));
  if (!tail.empty())
    sentences.push_back(std::move(tail));

  return sentences;
}

} // namespace piper
