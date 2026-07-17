from __future__ import annotations
import unicodedata as _ud
import re as _re
from dataclasses import dataclass
from typing import List, Tuple

# ---------- Unicode constants ----------
TAAMIM = r"[\u0591-\u05AF]"  # cantillation marks
NIQQUD_ALL = r"[\u0591-\u05C7]"  # cantillation + niqqud
DAGESH = "\u05BC"
SHIN_DOT = "\u05C1"
SIN_DOT = "\u05C2"
GERESH = "\u05F3"  # ׳
GERSHAYIM = "\u05F4"  # ״

# Niqqud
SHEVA = "\u05B0"
HATAF_SEGOL = "\u05B1"
HATAF_PATAH = "\u05B2"
HATAF_QAMATS = "\u05B3"
HIRIQ = "\u05B4"
TSERE = "\u05B5"
SEGOL = "\u05B6"
PATAH = "\u05B7"
QAMATS = "\u05B8"
HOLAM = "\u05B9"
QUBUTZ = "\u05BB"
QAMATS_QATAN = "\u05C7"  # explicit qamats qatan (rare but exists)

VOWEL_MARKS = {
    SHEVA,
    HATAF_SEGOL,
    HATAF_PATAH,
    HATAF_QAMATS,
    HIRIQ,
    TSERE,
    SEGOL,
    PATAH,
    QAMATS,
    HOLAM,
    QUBUTZ,
    QAMATS_QATAN,
}

# Base letters
ALEF = "א"
BET = "ב"
GIMEL = "ג"
DALET = "ד"
HE = "ה"
VAV = "ו"
ZAYIN = "ז"
HET = "ח"
TET = "ט"
YOD = "י"
KAF = "כ"
KAF_FINAL = "ך"
LAMED = "ל"
MEM = "מ"
MEM_FINAL = "ם"
NUN = "נ"
NUN_FINAL = "ן"
SAMEKH = "ס"
AYIN = "ע"
PE = "פ"
PE_FINAL = "ף"
TSADI = "צ"
TSADI_FINAL = "ץ"
QOF = "ק"
RESH = "ר"
SHIN = "ש"
TAV = "ת"

FINAL_FORM_BASE = {
    KAF_FINAL: KAF,
    MEM_FINAL: MEM,
    NUN_FINAL: NUN,
    PE_FINAL: PE,
    TSADI_FINAL: TSADI,
}

BEGADKEFAT = {
    BET,
    KAF,
    PE,
    TAV,
    DALET,
    GIMEL,
}  # only ב כ פ alternate in Israeli; others stable

# Map geresh digraphs first (single token replacements)
GERESH_DIGRAPHS = {
    GIMEL + GERESH: "d͡ʒ",
    ZAYIN + GERESH: "ʒ",
    TSADI + GERESH: "t͡ʃ",
}


# ---------- Helper data structures ----------
@dataclass
class Glyph:
    base: str
    marks: List[str]

    def has(self, mark: str) -> bool:
        return mark in self.marks

    def any(self, marks: set[str]) -> bool:
        return any(m in marks for m in self.marks)


def _nfc(s: str) -> str:
    return _ud.normalize("NFC", s)


def _strip_taamim(s: str) -> str:
    return _re.sub(TAAMIM, "", s)


def _iter_glyphs(word: str) -> List[Glyph]:
    """Split a Hebrew word into base letters + combining marks (niqqud/dots)."""
    word = _nfc(_strip_taamim(word))
    glyphs: List[Glyph] = []
    for ch in word:
        if _ud.combining(ch):
            if glyphs:
                glyphs[-1].marks.append(ch)
        else:
            glyphs.append(Glyph(ch, []))
    return glyphs


def _apply_geresh_digraphs(glyphs: List[Glyph]) -> List[Glyph]:
    """Collapse ג׳ ז׳ צ׳ into placeholder IPA tokens via special base tags."""
    out: List[Glyph] = []
    i = 0
    while i < len(glyphs):
        g = glyphs[i]
        if (
            i + 1 < len(glyphs)
            and glyphs[i + 1].base == GERESH
            and g.base + glyphs[i + 1].base
            in (GIMEL + GERESH, ZAYIN + GERESH, TSADI + GERESH)
        ):
            ipa = GERESH_DIGRAPHS[g.base + glyphs[i + 1].base]
            out.append(Glyph(f"<IPA:{ipa}>", []))
            i += 2
            continue
        out.append(g)
        i += 1
    return out


# ---------- Consonant mapping ----------
def _map_consonant(
    base: str, marks: List[str], is_final: bool, next_is_vowel: bool
) -> str:
    """Return IPA (possibly empty) for a consonant letter considering dots/dagesh."""
    b = FINAL_FORM_BASE.get(base, base)

    # Silent letters and special cases
    if b == ALEF or b == AYIN:
        # Realize glottal stop only when it separates vowels or hosts its own vowel
        # Actual decision is postponed to vowel handling; here return placeholder
        return "<GLT>"  # may collapse later
    if b == HE:
        # Final he without mappiq is silent
        if is_final and DAGESH not in marks:
            return ""
        return "h"
    if b == YOD:
        # Consonantal yod only if not part of ḥiriq-yod sequence (handled in vowels)
        # As consonant, map to /j/
        return "j"
    if b == VAV:
        # As consonant, /v/. If vowel (shuruk/holam male), handled in vowels.
        return "v"

    # Shin/Sin
    if b == SHIN:
        if SHIN_DOT in marks:
            return "ʃ"
        if SIN_DOT in marks:
            return "s"
        # default shin without dot in modern text -> ʃ
        return "ʃ"

    # Begadkefat alternations (only ב כ פ in Israeli)
    if b == BET:
        return "b" if DAGESH in marks else "v"
    if b == KAF:
        if DAGESH in marks:
            return "k"
        return "χ"
    if b == PE:
        return "p" if DAGESH in marks else "f"

    # Stable consonants
    if b == GIMEL:
        return "g"
    if b == DALET:
        return "d"
    if b == HET:
        return "χ"  # [χ~x]
    if b == TET:
        return "t"
    if b == LAMED:
        return "l"
    if b == MEM:
        return "m"
    if b == NUN:
        return "n"
    if b == SAMEKH:
        return "s"
    if b == TSADI:
        return "t͡s"
    if b == QOF:
        return "k"
    if b == RESH:
        return "ʁ"  # Israeli
    if b == TAV:
        return "t"
    if b == ZAYIN:
        return "z"

    return ""


# ---------- Vowel nucleus mapping ----------
def _is_vowel_mark(m: str) -> bool:
    return m in VOWEL_MARKS


def _has_vowel_marks(marks: List[str]) -> bool:
    return any(_is_vowel_mark(m) for m in marks)


def _is_hiriq_yod(curr: Glyph, nxt: Glyph | None) -> bool:
    return (
        curr.has(HIRIQ)
        and nxt is not None
        and nxt.base == YOD
        and not _has_vowel_marks(nxt.marks)
    )


def _is_holam_male(g: Glyph) -> bool:
    # Holam sits on the vav (חוֹ) — the vav is a mater, nucleus /o/, no /v/.
    return g.base == VAV and g.has(HOLAM) and not g.has(DAGESH)


def _is_shuruk(curr: Glyph) -> bool:
    # וּ (vav + dagesh) with no other vowel marks
    return (
        curr.base == VAV
        and curr.has(DAGESH)
        and not any(
            m
            in {
                HOLAM,
                HIRIQ,
                TSERE,
                SEGOL,
                PATAH,
                QAMATS,
                QUBUTZ,
                QAMATS_QATAN,
                SHEVA,
                HATAF_SEGOL,
                HATAF_PATAH,
                HATAF_QAMATS,
            }
            for m in curr.marks
        )
    )


def _map_basic_vowel(g: Glyph) -> Tuple[str, bool]:
    """Return (ipa, is_vocalic) from marks on current glyph (not including mater cases)."""
    if g.has(QAMATS_QATAN):
        return "o", True
    if g.has(QUBUTZ):
        return "u", True
    if g.has(HIRIQ):
        return "i", True
    if g.has(TSERE):
        return "e", True
    if g.has(SEGOL):
        return "e", True
    if g.has(PATAH):
        return "a", True
    if g.has(QAMATS):  # undecided a/o; tentatively 'a' (fix with qatan heuristic later)
        return "a", True
    if g.has(HATAF_PATAH):
        return "a", True
    if g.has(HATAF_SEGOL):
        return "e", True
    if g.has(HATAF_QAMATS):
        return "o", True
    if g.has(SHEVA):
        return "ə", False  # may become ∅ if sheva nach
    return "", False


# ---------- Core conversion per word ----------
@dataclass
class Segment:
    onset: List[str]  # consonant IPA (may include placeholders like <GLT>)
    nucleus: str  # vowel ipa ('a e i o u ə' or '')
    coda: List[str]


def _word_to_segments(word: str) -> List[Segment]:
    """Parse a diacritized word into syllable-like segments with rough nucleus detection."""
    glyphs = _apply_geresh_digraphs(_iter_glyphs(word))

    segs: List[Segment] = []
    onset: List[str] = []
    i = 0
    while i < len(glyphs):
        g = glyphs[i]
        nxt = glyphs[i + 1] if i + 1 < len(glyphs) else None
        is_final = i == len(glyphs) - 1

        # Handle vowel cases that span two glyphs (ḥolam male, hiriq-yod, shuruk)
        if _is_shuruk(g):
            # vowel nucleus /u/
            if not onset:
                onset = []
            segs.append(Segment(onset, "u", []))
            onset = []
            i += 1
            continue
        if _is_hiriq_yod(g, nxt):
            cons = _map_consonant(g.base, g.marks, is_final=False, next_is_vowel=True)
            # HIRIQ under current consonant belongs to nucleus /i/
            if cons and cons != "<GLT>":
                onset.append(cons)
            segs.append(Segment(onset, "i", []))
            onset = []
            i += 2  # skip YOD
            continue
        if _is_holam_male(g):
            # The vav itself is the /o/ vowel; the pending onset consonant(s)
            # attach to it. The vav produces no /v/.
            segs.append(Segment(onset, "o", []))
            onset = []
            i += 1
            continue

        # Otherwise, map consonant
        cons = _map_consonant(g.base, g.marks, is_final=is_final, next_is_vowel=False)
        # Check local vowel on same glyph
        v, is_voc = _map_basic_vowel(g)

        if is_voc:
            # consonant (if any) -> onset, vowel -> nucleus
            if cons and cons != "<GLT>":
                onset.append(cons)
            segs.append(Segment(onset, v, []))
            onset = []
        else:
            # No vowel mark (or only sheva which we'll resolve later)
            if g.has(SHEVA):
                # Temporary nucleus 'ə' to resolve as na'/nach later
                if cons and cons != "<GLT>":
                    onset.append(cons)
                segs.append(Segment(onset, "ə", []))
                onset = []
            else:
                # Pure consonant (may be mater or silent letters)
                if cons == "<GLT>":
                    # defer; store as onset to create hiatus if between nuclei
                    onset.append("ʔ")  # realize glottal if it separates vowels
                elif cons:
                    onset.append(cons)
        i += 1

    # Any trailing onset without vowel becomes coda of the last segment
    if onset and segs:
        segs[-1].coda.extend(onset)
        onset = []
    return segs


def _resolve_sheva_and_qamats(segs: List[Segment]) -> List[Segment]:
    """Apply practical sheva-na/nach and qamats-qatan heuristics."""
    # Sheva: treat 'ə' as:
    # - word-initial nucleus -> ə (na')
    # - first of two consecutive 'ə' nuclei -> ə; the second -> ∅ (attach its onset to next)
    # - before impossible cluster -> ə
    # - otherwise, final 'ə' -> ∅ (nach)
    for i, s in enumerate(segs):
        if s.nucleus != "ə":
            continue
        is_first = i == 0
        is_last = i == len(segs) - 1
        prev_has_vowel = i - 1 >= 0 and segs[i - 1].nucleus not in ("",)

        make_schwa = False
        if is_first:
            make_schwa = True
        elif i + 1 < len(segs) and segs[i + 1].nucleus == "ə":
            # first of two consecutive shevas -> ə; second processed next loop
            make_schwa = True
        elif is_last:
            make_schwa = False
        else:
            # Favor ə if previous nucleus is long (e,i,o,u) to avoid heavy clusters
            if prev_has_vowel and segs[i - 1].nucleus in ("e", "i", "o", "u"):
                make_schwa = True
            else:
                # If onset would be too big (>=2), prefer ə
                if len(s.onset) >= 2:
                    make_schwa = True

        if not make_schwa:
            # turn into ∅: push its onset to coda of previous syllable if exists
            if i - 1 >= 0:
                segs[i - 1].coda.extend(s.onset)
            s.onset = []
            s.nucleus = ""

    # Collapse empty-nucleus segments by merging onsets/codas
    merged: List[Segment] = []
    for s in segs:
        if s.nucleus == "":
            if merged:
                merged[-1].coda.extend(s.onset)
            else:
                # Rare case: word starts with consonant cluster and no vowel: keep in onset of next
                merged.append(s)
            continue
        merged.append(s)

    segs = merged

    # Qamats qatan: set 'a' -> 'o' when in closed, unstressed (approximate) syllable.
    # We'll mark qatan when the vowel came from QAMATS and:
    # - syllable is closed (has coda), and
    # - not the last syllable (approximate "unstressed")
    # Because we lost the original mark, we approximate by common patterns on lexemes later if needed.
    # Here, we apply a heuristic: any 'a' nucleus with non-empty coda and not last -> 'o'.
    for i, s in enumerate(segs):
        if s.nucleus == "a" and s.coda and i < len(segs) - 1:
            s.nucleus = "o"

    return segs


def _syllabify_to_ipa(segs: List[Segment]) -> Tuple[str, List[Tuple[int, int]]]:
    """Join segments to IPA string and compute stress placement.
    Returns (ipa, syllable_spans) where spans are offsets (start,end) in the string for each syllable nucleus.
    """
    # Build syllable strings with maximal onset preference already in segments
    syls: List[str] = []
    for s in segs:
        syl = "".join(s.onset) + s.nucleus + "".join(s.coda)
        syls.append(syl)
    # Stress: default ultimate (last syllable), with a simple segholate exception:
    # if there are exactly 2 syllables and the last ends with a final consonant (coda non-empty),
    # stress penultimate.
    stress_index = len(syls) - 1
    if len(syls) == 2 and segs[-1].coda:
        stress_index = 0

    # Assemble with stress marker before the stressed syllable's vowel nucleus
    pieces = []
    for idx, s in enumerate(segs):
        syl = "".join(s.onset) + s.nucleus + "".join(s.coda)
        if idx == stress_index:
            # Insert ˈ before the vowel symbol (nucleus)
            before = "".join(s.onset)
            after = "".join(s.coda)
            syl = before + "ˈ" + s.nucleus + after
        pieces.append(syl)
    ipa = "".join(pieces)
    return ipa, []


def hebrew_word_to_ipa(word: str) -> str:
    """Convert a single fully-diacritized Hebrew word to IPA."""
    segs = _word_to_segments(word)
    segs = _resolve_sheva_and_qamats(segs)
    ipa, _ = _syllabify_to_ipa(segs)

    # Cleanup: remove placeholder redundant glottals that ended up adjacent to consonants
    ipa = _re.sub(r"ʔ(?=ˈ?[aeiouə])", "ʔ", ipa)  # keep before vowels
    ipa = _re.sub(r"(?<=^)ʔ", "ʔ", ipa)  # keep word-initial if present
    ipa = _re.sub(r"ʔ(?=[^aeiouəˈ]|$)", "", ipa)  # drop before consonants/end
    # Drop the affricate tie bar so t͡s/t͡ʃ/d͡ʒ become plain phoneme pairs that
    # exist in Piper's default IPA id map.
    ipa = ipa.replace("͡", "")
    return ipa


def hebrew_to_ipa(text: str) -> str:
    """Convert a sentence (space-separated words) to IPA."""
    text = _nfc(_strip_taamim(text))
    words = text.split()
    out = []
    for w in words:
        out.append(hebrew_word_to_ipa(w))
    return " ".join(out)
