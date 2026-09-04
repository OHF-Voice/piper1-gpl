"""Thai phonemization: TLTK grapheme-to-phoneme -> IPA + tone digits.

espeak-ng's Thai voice is a placeholder that cannot be trained on. The
maintainer who added it said so when he landed it (espeak-ng#757): the phonemes
and tones were copied from Shan, "many of tones are probably set wrong", and the
rules in ``th_list``/``th_rules`` are "very simple just to hear something". In
practice ``th_dict`` carries no lexicon (2 KB, one of the smallest in
espeak-ng), so there is no word segmentation for a script written without
spaces; the leading vowels เ แ โ ใ ไ are emitted in writing order instead of
being reordered after their consonant (เขา comes out as "e-kha"); no tone is
ever produced; and a tone mark deletes the syllable's vowel outright, so
ป่า/ป้า/ป๊า/ป๋า all collapse to the same phonemes. Measured over the TSync2
corpus, ~11% of the tokens espeak-ng returns contain no vowel at all.

TLTK (BSD-3-Clause) does dictionary-based word segmentation and returns
syllabified IPA with an explicit tone per syllable, which is what Thai actually
needs: it has five phonemic tones and minimal pairs are everywhere
(ข่าว "news" vs ข้าว "rice").

Tones are emitted as the digits 1-5 -- 1 mid, 2 low, 3 falling, 4 high, 5
rising -- one per syllable, immediately after that syllable's segments. This is
the representation :mod:`piper.phonemize_chinese` already uses for Mandarin
tones. Every symbol produced here is a single codepoint that already has an id
in :data:`piper.phoneme_ids.DEFAULT_PHONEME_ID_MAP`, so Thai voices stay
compatible with the IPA-based (espeak) warmstart -- the same trick
:mod:`piper.phonemize_hebrew` and :mod:`piper.phonemize_japanese` use.

Requires ``pip install tltk unicode-rbnf`` (the ``th`` extra).
"""

import logging
import re
import unicodedata
from typing import Dict, List, Optional

from .phoneme_ids import DEFAULT_PHONEME_ID_MAP

_LOGGER = logging.getLogger(__name__)

# Thai tones, one digit per syllable. TLTK numbers them 1=mid (สามัญ), 2=low
# (เอก), 3=falling (โท), 4=high (ตรี), 5=rising (จัตวา).
TONES = frozenset("12345")

# TLTK spells the open-o with U+1D10 LATIN LETTER SMALL CAPITAL OPEN O, which is
# not the IPA character and has no phoneme id. It means U+0254 LATIN SMALL
# LETTER OPEN O. This single substitution is what makes TLTK's entire inventory
# land inside the default IPA id map.
_TLTK_TO_IPA: Dict[str, str] = {"ᴐ": "ɔ"}

# TLTK marks the end of each chunk it transcribed with this.
_CHUNK_MARKER = "<s/>"

# Runs of Thai we hand to TLTK: consonants, vowels, tone marks, and mai yamok
# (ๆ, the repetition mark, which TLTK expands itself). Deliberately excludes
# U+0E2F (ฯ) and the other Thai punctuation handled in _SILENT below -- TLTK
# reads them out by name ("ไปยาลน้อย") rather than treating them as marks.
_THAI_RUN = re.compile(r"[ก-ฮะ-ฺเ-๎]+")

# ฯลฯ ("et cetera") is read aloud as ละ. Handled before ฯ is stripped below,
# which would otherwise leave the bare ล to be read as a syllable.
_ET_CETERA = ("ฯลฯ", "ละ")

# Thai abbreviation and section marks that should not be spoken, plus the
# zero-width characters unicode-rbnf inserts between number words. A single one
# of these left inside a run makes TLTK return an empty transcription for the
# whole run, so they are stripped before segmentation rather than after. Note
# that ๆ is *not* stripped: TLTK expands it correctly when it follows a word
# (เด็กๆ -> dek2 dek2), which is the only place it can legally appear.
_SILENT = re.compile("[ฯ๏๚๛\u200b\u200c\u200d\ufeff]")

# Obsolete letters that are absent from TLTK's dictionary. Both were merged into
# their surviving counterparts in modern orthography (ฃ -> ข, ฅ -> ค).
_OBSOLETE = str.maketrans({"ฃ": "ข", "ฅ": "ค"})

_THAI_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")

# สระอำ (U+0E33) is sometimes typed as its two visual parts, nikhahit + sara aa,
# with any tone mark wedged between them: คร่ำ as ค ร ํ ่ า. Unicode gives
# U+0E33 no canonical decomposition, so NFC does not repair this, and TLTK
# transcribes the whole run as empty when it sees one -- which silently costs a
# whole utterance, since unspaced Thai is a single run.
_SARA_AM = re.compile("ํ([่-๋]?)า")

# Thousands separators inside a number, so 1,250 expands as one number.
_GROUPED_NUMBER = re.compile(r"(?<=\d),(?=\d{3}\b)")
# The leading minus only counts at a word boundary, so the hyphen in a compound
# like โควิด-19 stays a hyphen instead of turning the number negative.
_NUMBER = re.compile(r"(?<!\w)-?\d+(?:\.\d+)?")
_BAHT = re.compile(r"฿\s*(-?[\d.]+)")
_PERCENT = re.compile(r"(-?[\d.]+)\s*%")

# Punctuation kept as phonemes. These all have ids in the default map and give
# the duration predictor its pause and intonation cues.
_PUNCTUATION = frozenset(".,?!:;-")

# Thai has no sentence-final period natively; these corpora carry no punctuation
# at all, and a lone space is a clause break rather than a sentence break. So we
# split only on explicit terminal punctuation and newlines instead of reaching
# for a general sentence splitter.
_SENTENCE_SPLIT = re.compile(r"(?<=[.?!])\s+|\n+")

_WORD_BREAK = " "


class ThaiPhonemizer:
    """Convert Thai text to IPA phonemes with per-syllable tone digits."""

    def __init__(self, expand_numbers: bool = True) -> None:
        """Initialize the phonemizer.

        :param expand_numbers: Spell digits out as Thai words before
            segmentation. TLTK does not read numbers -- it transcribes "1250"
            as the phonemes "2351" -- so this is on by default.
        """
        from tltk.nlp import th2ipa  # noqa: F401  (loads TLTK's dictionary)

        self._th2ipa = th2ipa

        self.number_engine = None
        if expand_numbers:
            from unicode_rbnf import RbnfEngine

            self.number_engine = RbnfEngine.for_language("th")

    def phonemize(self, text: str) -> List[List[str]]:
        """Return IPA phonemes with tone digits, grouped by sentence.

        Each phoneme is a single codepoint, matching how espeak phonemes are
        keyed in :data:`piper.phoneme_ids.DEFAULT_PHONEME_ID_MAP`.
        """
        all_phonemes: List[List[str]] = []

        for sentence in _SENTENCE_SPLIT.split(text):
            sentence_phonemes = self._phonemize_sentence(sentence)
            if sentence_phonemes:
                all_phonemes.append(sentence_phonemes)

        return all_phonemes

    def _phonemize_sentence(self, sentence: str) -> List[str]:
        sentence = self._normalize(sentence)

        phonemes: List[str] = []
        position = 0

        for match in _THAI_RUN.finditer(sentence):
            phonemes.extend(_punctuation_phonemes(sentence[position : match.start()]))
            phonemes.extend(self._phonemize_run(match.group()))
            position = match.end()

        phonemes.extend(_punctuation_phonemes(sentence[position:]))

        # A leading word break carries no information and costs a frame.
        while phonemes and phonemes[0] == _WORD_BREAK:
            phonemes.pop(0)

        while phonemes and phonemes[-1] == _WORD_BREAK:
            phonemes.pop()

        return phonemes

    def _phonemize_run(self, run: str) -> List[str]:
        """Segment and transcribe one contiguous run of Thai letters.

        Runs are fed to TLTK one at a time. Anything else -- spaces, Latin
        letters, punctuation -- makes ``th2ipa`` raise ``ValueError: too many
        values to unpack``, which silently loses whole utterances if the input
        is pre-segmented (it drops 70% of the Porjai corpus, whose transcripts
        are space-delimited). One run per call sidesteps that, and TLTK still
        does its own word segmentation inside the run, which is the part we
        actually want.
        """
        try:
            transcription = self._th2ipa(run)
        except Exception:
            _LOGGER.warning("TLTK could not transcribe Thai run: %s", run)
            return []

        phonemes: List[str] = []

        # TLTK separates words with spaces and its own chunks with <s/>; both
        # are word breaks for us. Syllables within a word are separated by "."
        # and the parts of a spelled-out symbol by "+".
        for word in transcription.replace(_CHUNK_MARKER, " ").split():
            word_phonemes: List[str] = []

            for syllable in re.split(r"[.+]", word):
                word_phonemes.extend(self._syllable_phonemes(syllable, run))

            if word_phonemes:
                if phonemes:
                    phonemes.append(_WORD_BREAK)

                phonemes.extend(word_phonemes)

        if not phonemes:
            # TLTK returns an empty transcription rather than raising when it
            # cannot segment a run, and unspaced Thai is one run per utterance,
            # so staying quiet here would silently drop whole utterances.
            _LOGGER.warning("No phonemes for Thai run: %s", run)

        return phonemes

    def _syllable_phonemes(self, syllable: str, run: str) -> List[str]:
        # Silent letters (การันต์) leave empty syllables behind, e.g. พิมพ์ is
        # transcribed "pʰim1..".
        if not syllable:
            return []

        tone: Optional[str] = None
        if syllable[-1] in TONES:
            syllable, tone = syllable[:-1], syllable[-1]

        phonemes: List[str] = []
        for char in syllable:
            char = _TLTK_TO_IPA.get(char, char)

            if char not in DEFAULT_PHONEME_ID_MAP:
                # A word TLTK could not transcribe is echoed back verbatim, so
                # this is where out-of-vocabulary Thai gets dropped instead of
                # becoming junk phoneme ids.
                _LOGGER.warning(
                    "Dropping untranscribed symbol %r from Thai run: %s", char, run
                )
                return []

            phonemes.append(char)

        if not phonemes:
            return []

        if tone is not None:
            phonemes.append(tone)

        return phonemes

    def _normalize(self, text: str) -> str:
        # Thai combining marks only compose correctly in canonical order.
        text = unicodedata.normalize("NFC", text)
        text = text.translate(_THAI_DIGITS).translate(_OBSOLETE)
        text = _SARA_AM.sub("\\1ำ", text)
        text = text.replace(*_ET_CETERA)

        if self.number_engine is not None:
            text = self._numbers_to_words(text)

        # Any zero-width character still here came from the input text rather
        # than from number expansion, which turns its own into real spaces.
        return _SILENT.sub("", text)

    def _numbers_to_words(self, text: str) -> str:
        text = _GROUPED_NUMBER.sub("", text)
        text = _BAHT.sub(lambda m: f"{m.group(1)} บาท", text)
        text = _PERCENT.sub(lambda m: f"{m.group(1)} เปอร์เซ็นต์", text)
        text = _NUMBER.sub(self._th_number, text)

        # unicode-rbnf joins number words with zero-width spaces. Turn them into
        # real spaces so each word becomes its own run: TLTK's segmenter drops
        # the tail of some compounds when it has to split them itself
        # (สิบเก้า "nineteen" comes back as just "si2").
        return text.replace("\u200b", " ")

    def _th_number(self, match: re.Match) -> str:
        assert self.number_engine is not None
        try:
            return self.number_engine.format_number(match.group(0)).text
        except Exception:
            _LOGGER.warning("Could not spell out number: %s", match.group(0))
            return ""


def _punctuation_phonemes(text: str) -> List[str]:
    """Turn the non-Thai text between two runs into break phonemes.

    Everything unrecognized (Latin letters, emoji, stray symbols) collapses to a
    single word break rather than being passed through, so it can never reach
    the id map.
    """
    phonemes: List[str] = []

    for char in text:
        if char in _PUNCTUATION:
            phonemes.append(char)
            continue

        if char.isalnum():
            # Latin words, leftover digits: nothing sensible to say in Thai.
            _LOGGER.warning("Dropping non-Thai character: %r", char)

        if not phonemes or phonemes[-1] != _WORD_BREAK:
            phonemes.append(_WORD_BREAK)

    return phonemes
