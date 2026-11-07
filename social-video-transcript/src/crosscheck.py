"""Cross-check: the same audio recognised by the second Whisper model, and the places where the two disagree.

Noise (wind, music, crowd) breaks numbers and short words, and the two models usually break them differently, so a
disagreement marks a place worth listening to. Where both agree, they can still both be wrong."""
from __future__ import annotations

import difflib
import re

_WORD = re.compile(r"[\w'’]+(?:[.,:-][\w'’]+)*", re.UNICODE)
_CONTRACTIONS = {"n't": ' not', "'re": ' are', "'ll": ' will', "'ve": ' have', "'m": ' am', "'d": ' would'}
_IRREGULAR = {"can't": 'can not', "won't": 'will not', "cannot": 'can not'}
_IS = {"it's", "that's", "there's", "here's", "what's", "he's", "she's", "who's", "where's", "let's"}
_NUMBER_WORDS = set('zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen '
                    'sixteen seventeen eighteen nineteen twenty thirty forty fifty sixty seventy eighty ninety '
                    'hundred thousand million billion percent'.split())
MAX_DIFFERENCES = 200
MERGE_GAP = 2  # differences this few equal words apart are one place ("17, even 18" against "70, even 80")


def _norm(token: str) -> list[str]:
    """One spoken word as comparable pieces: case, apostrophes and English contractions do not count."""
    t = token.lower().replace('’', "'").strip("'")
    if t in _IS:
        return ['let', 'us'] if t == "let's" else [t[:-2], 'is']
    if t in _IRREGULAR:
        t = _IRREGULAR[t]
    else:
        for short, full in _CONTRACTIONS.items():
            if t.endswith(short) and len(t) > len(short):
                t = t[:-len(short)] + full
                break
    t = t.replace("'", '')
    return [p for p in re.split(r'[\s.,:-]+', t) if p]


def _words(segments: list[dict]) -> tuple[list[str], list[tuple[int, int]], list[str]]:
    """Comparable pieces, and for each one (segment index, index of the original word in the flat word list)."""
    pieces, where, originals = [], [], []
    for si, seg in enumerate(segments):
        for m in _WORD.finditer(seg.get('text') or ''):
            originals.append(m.group(0))
            for p in _norm(m.group(0)):
                pieces.append(p)
                where.append((si, len(originals) - 1))
    return pieces, where, originals


def _has_number(text: str) -> bool:
    return bool(re.search(r'\d', text)) or any(w in _NUMBER_WORDS for w in re.findall(r'[a-z]+', text.lower()))


def compare(primary: list[dict], other: list[dict]) -> dict:
    """{'agreement': share of matching words, 'differences': [{'start', 'end', 'text', 'other', 'numbers'}]}.
    Times and 'text' come from the primary transcript, 'other' from the second model."""
    a, a_at, a_words = _words(primary)
    b, b_at, b_words = _words(other)
    if not a and not b:
        return {'agreement': 1.0, 'differences': []}
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    places = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'equal':
            continue
        if places and i1 - places[-1][1] <= MERGE_GAP and j1 - places[-1][3] <= MERGE_GAP:
            places[-1][1], places[-1][3] = i2, j2
        else:
            places.append([i1, i2, j1, j2])
    out = []
    for i1, i2, j1, j2 in places[:MAX_DIFFERENCES]:
        if i2 > i1:
            seg_from, seg_to = primary[a_at[i1][0]], primary[a_at[i2 - 1][0]]
        elif a:   # a word only the second model heard: the primary segment where it would stand
            seg_from = seg_to = primary[a_at[min(i1, len(a) - 1)][0]]
        else:
            seg_from, seg_to = other[b_at[j1][0]], other[b_at[j2 - 1][0]]
        if ''.join(a[i1:i2]) == ''.join(b[j1:j2]):
            continue      # only spacing differs: "south-west" and "southwest"
        text = ' '.join(a_words[k] for k in dict.fromkeys(a_at[x][1] for x in range(i1, i2)))
        alt = ' '.join(b_words[k] for k in dict.fromkeys(b_at[x][1] for x in range(j1, j2)))
        out.append({'start': seg_from['start'], 'end': seg_to['end'], 'text': text, 'other': alt,
                    'numbers': _has_number(text + ' ' + alt)})
    matched = sum(block.size for block in sm.get_matching_blocks())
    return {'agreement': round(2 * matched / (len(a) + len(b)), 3), 'differences': out}
