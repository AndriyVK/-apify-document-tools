"""Ukrainian word stress for Piper voices.

espeak-ng (Piper's phonemizer) has no Ukrainian stress dictionary and often stresses the wrong syllable
(«тЕлефон», «кОроль»). ukrainian-word-stress (MIT, lang-uk) finds the stress from a dictionary and the sentence
context; this module moves espeak's stress mark to that vowel. Words the dictionary does not know, and sentences
whose words cannot be matched one-to-one with espeak's output (e.g. digits expanded to several words), keep
espeak's stress.
"""
from __future__ import annotations

import os
import re

import numpy as np

STRESS = '́'
TEXT_VOWELS = set('аеєиіїоуюяАЕЄИІЇОУЮЯ')
IPA_VOWELS = set('aɑɐeɛəiɪɨoɔuʊyʉæ')
WORD = re.compile(r"[\w'’ʼ́-]+")
_stressifier = None
_trie = None
LITE_WORD = re.compile("[А-Яа-яІіЇїЄєҐґ'’ʼ]+")


def _stressify_lite(text: str) -> str:
    """Dictionary lookup without stanza's grammar parse (~30 MB instead of ~900 MB of memory). Ambiguous words get
    the dictionary's first variant; measured 27.10.2026: 2.8% of words differ from the full mode, about two thirds
    of them in the full mode's favour."""
    global _trie
    import os

    import marisa_trie
    import ukrainian_word_stress.stressify_ as sm
    from ukrainian_word_stress import OnAmbiguity
    if _trie is None:
        _trie = marisa_trie.BytesTrie()
        _trie.load(os.path.join(os.path.dirname(sm.__file__), 'data', 'stress.trie'))
    out, last = [], 0
    for m in LITE_WORD.finditer(text):
        w = m.group(0)
        out.append(text[last:m.start()])
        last = m.end()
        values = sm._trie_value(_trie, w)
        accents = sm._accent_positions_from_values(values, {'text': w}, OnAmbiguity.First) if values else []
        out.append(w[:accents[0]] + STRESS + w[accents[0]:] if accents else w)
    out.append(text[last:])
    return ''.join(out)


def _stressify(text: str) -> str:
    """Dictionary stress; for words with several possible stresses the dictionary's first variant (skipping them
    would leave espeak's guess, which is wrong far more often). UK_STRESS_MODE=lite skips the grammar parse."""
    global _stressifier
    if os.environ.get('UK_STRESS_MODE') == 'lite':
        return _stressify_lite(text)
    if _stressifier is None:
        from ukrainian_word_stress import OnAmbiguity, StressSymbol, Stressifier
        _stressifier = Stressifier(stress_symbol=StressSymbol.CombiningAcuteAccent, on_ambiguity=OnAmbiguity.First)
    return _stressifier(text)


def stressed_vowel_index(word: str) -> int | None:
    """Index of the stressed vowel among the word's vowels, from a word with a combining acute accent."""
    n = 0
    for i, ch in enumerate(word):
        if ch in TEXT_VOWELS:
            if i + 1 < len(word) and word[i + 1] == STRESS:
                return n
            n += 1
    return None


def restress(phoneme_words: list[list[str]], stressed_words: list[str]) -> tuple[list[list[str]], int]:
    """Moves the primary stress of each phoneme word to the dictionary's vowel. Returns (words, changes)."""
    out, changes = [], 0
    for ph, word in zip(phoneme_words, stressed_words):
        k = stressed_vowel_index(word)
        vowels = [i for i, p in enumerate(ph) if p in IPA_VOWELS]
        if k is None or k >= len(vowels) or sum(1 for c in word if c in TEXT_VOWELS) != len(vowels):
            out.append(ph)
            continue
        old = [i for i, p in enumerate(ph) if p == 'ˈ']
        new = [p for p in ph if p not in ('ˈ', 'ˌ')]
        target = [i for i, p in enumerate(new) if p in IPA_VOWELS][k]
        new.insert(target, 'ˈ')
        if not old or [i for i, p in enumerate(new) if p == 'ˈ'] != old:
            changes += 1
        out.append(new)
    return out, changes


def unstressed_words(text: str) -> list[str]:
    """Words of two or more syllables that the dictionary could not stress (names, loanwords, ambiguous forms)."""
    out = []
    for w in WORD.findall(_stressify(text)):
        if STRESS not in w and sum(c in TEXT_VOWELS for c in w) >= 2 and w.lower() not in out:
            out.append(w.lower())
    return out


def phonemize_uk(voice, text: str, overrides: dict[str, str] | None = None) -> tuple[list[list[str]], int]:
    """Sentence phonemes with dictionary stress; returns (sentences, number of words whose stress was moved).
    overrides: lower-case word -> the same word with a combining acute accent, for words the dictionary does not
    stress (e.g. from a language model)."""
    stressed = _stressify(text)
    if overrides:
        def fix(m):
            w = m.group(0)
            o = overrides.get(w.lower())
            plain = w.replace(STRESS, '')
            if not o or o.replace(STRESS, '') != plain.lower():
                return w
            i = o.index(STRESS)  # keep the original capitalisation
            return plain[:i] + STRESS + plain[i:]
        stressed = WORD.sub(fix, stressed)
    total = 0
    result = []
    plain_sentences = voice.phonemize(text)
    # Piper splits sentences itself; stress words are matched over the whole text in order
    words = WORD.findall(stressed)
    pos = 0
    for sent in plain_sentences:
        groups, cur = [], []
        for p in sent:
            if p == ' ':
                if cur:
                    groups.append(cur)
                cur = []
            else:
                cur.append(p)
        if cur:
            groups.append(cur)
        # punctuation phonemes stick to words; split them off for matching and put them back
        core = [[p for p in g if p not in ',.!?;:—…"«»()'] for g in groups]
        tail = [[p for p in g if p in ',.!?;:—…"«»()'] for g in groups]
        n = len([c for c in core if c])
        chunk = words[pos:pos + n]
        if len(chunk) == n and all(core):
            fixed, changes = restress(core, chunk)
            total += changes
            groups = [f + t for f, t in zip(fixed, tail)]
        pos += n
        flat = []
        for i, g in enumerate(groups):
            if i:
                flat.append(' ')
            flat.extend(g)
        result.append(flat)
    return result, total


def synthesize_uk(voice, text: str, syn_config=None, overrides: dict[str, str] | None = None) -> tuple[bytes, int]:
    """16-bit mono PCM for Ukrainian text with dictionary stress; returns (pcm, stress changes)."""
    sentences, changes = phonemize_uk(voice, text, overrides)
    chunks = []
    for ph in sentences:
        if not ph:
            continue
        audio = voice.phoneme_ids_to_audio(voice.phonemes_to_ids(ph), syn_config)
        if isinstance(audio, tuple):
            audio = audio[0]
        peak = float(np.max(np.abs(audio))) or 1.0
        chunks.append((np.clip(audio / peak, -1, 1) * 32767).astype(np.int16).tobytes())
    return b''.join(chunks), changes
