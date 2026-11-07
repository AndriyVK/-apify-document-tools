"""Cross-check: the same audio recognised by the second Whisper model, and the places where the two disagree.

Noise (wind, music, crowd) breaks numbers and short words, and the two models usually break them differently, so a
disagreement marks a place worth listening to. Where both agree, they can still both be wrong."""
from __future__ import annotations

import bisect
import re

_WORD = re.compile(r"[\w'’]+(?:[.,:-][\w'’]+)*", re.UNICODE)
_CONTRACTIONS = {"n't": ' not', "'re": ' are', "'ll": ' will', "'ve": ' have', "'m": ' am', "'d": ' would'}
_IRREGULAR = {"can't": 'can not', "won't": 'will not', "cannot": 'can not'}
_IS = {"it's", "that's", "there's", "here's", "what's", "he's", "she's", "who's", "where's", "let's"}
_NUMBER_WORDS = set('zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen '
                    'sixteen seventeen eighteen nineteen twenty thirty forty fifty sixty seventy eighty ninety '
                    'hundred thousand million billion percent'.split())
_DIGITS = {w: str(n) for n, w in enumerate('zero one two three four five six seven eight nine ten eleven twelve thirteen '
                                         'fourteen fifteen sixteen seventeen eighteen nineteen twenty'.split())}
_DIGITS.update({w: str(30 + 10 * n) for n, w in enumerate('thirty forty fifty sixty seventy eighty ninety'.split())})
_DIGITS.update(dict.fromkeys(['percent', 'відсоток', 'відсотки', 'відсотків', 'відсотка', 'процент', 'процента',
                               'процентов', 'проценты'], '%'))
MAX_DIFFERENCES = 200
WINDOW = 15.0  # seconds: the two models time the same word within a few seconds of each other
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
    return [_DIGITS.get(p, p) for p in re.split(r'[\s.,:-]+', t) if p]


def _numbers(text: str) -> str:
    """1,240 and 1240, 12% and 12 percent are the same words."""
    text = re.sub(r'(?<=\d)[,.\u00a0 ](?=\d{3}(?!\d))', '', text)
    return re.sub(r'(?<=\d)\s*%', ' percent', text)   # 'percent' and its Ukrainian and Russian words become '%'


def _words(segments: list[dict]) -> tuple[list[str], list[tuple[int, int]], list[str], list[float]]:
    """Comparable pieces; for each one (segment index, index of the original word) and its estimated time: words are
    spread evenly over their segment."""
    pieces, where, originals, times = [], [], [], []
    for si, seg in enumerate(segments):
        found = list(_WORD.finditer(_numbers(seg.get('text') or '')))
        start, end = float(seg.get('start') or 0), float(seg.get('end') or 0)
        for k, m in enumerate(found):
            originals.append(m.group(0))
            at = start + (max(end, start) - start) * (k + 0.5) / len(found)
            for p in _norm(m.group(0)):
                pieces.append(p)
                where.append((si, len(originals) - 1))
                times.append(at)
    return pieces, where, originals, times


def _align(a: list[str], ta: list[float], b: list[str], tb: list[float]) -> list[tuple[str, int, int]]:
    """Edit-distance alignment where a word may only be paired with words said within WINDOW seconds of it, so a
    repeated passage is not matched with its other repetition. Returns ('equal'|'replace'|'delete'|'insert', i, j)."""
    n, m = len(a), len(b)
    lo, hi = [0] * (n + 1), [0] * (n + 1)
    hi[0] = bisect.bisect_right(tb, (ta[0] if n else 0) + WINDOW)
    for i in range(1, n + 1):
        lo[i] = min(max(bisect.bisect_left(tb, ta[i - 1] - WINDOW), lo[i - 1]), hi[i - 1])
        hi[i] = max(bisect.bisect_right(tb, ta[i - 1] + WINDOW), hi[i - 1])
    hi[n] = m
    inf = float('inf')
    cost, back = [], []
    for i in range(n + 1):
        row, brow = [inf] * (hi[i] - lo[i] + 1), [''] * (hi[i] - lo[i] + 1)
        for j in range(lo[i], hi[i] + 1):
            best, how = (0.0, '') if i == 0 and j == 0 else (inf, '')
            if i and lo[i - 1] <= j - 1 <= hi[i - 1]:
                c = cost[i - 1][j - 1 - lo[i - 1]] + (0 if a[i - 1] == b[j - 1] else 1)
                if c < best:
                    best, how = c, 'equal' if a[i - 1] == b[j - 1] else 'replace'
            if i and lo[i - 1] <= j <= hi[i - 1] and cost[i - 1][j - lo[i - 1]] + 1 < best:
                best, how = cost[i - 1][j - lo[i - 1]] + 1, 'delete'
            if j > lo[i] and row[j - 1 - lo[i]] + 1 < best:
                best, how = row[j - 1 - lo[i]] + 1, 'insert'
            row[j - lo[i]], brow[j - lo[i]] = best, how
        cost.append(row)
        back.append(brow)
    ops, i, j = [], n, m
    while i or j:
        how = back[i][j - lo[i]]
        if how in ('equal', 'replace'):
            i, j = i - 1, j - 1
        elif how == 'delete':
            i -= 1
        else:
            j -= 1
        ops.append((how, i, j))
    return ops[::-1]


def _has_number(text: str) -> bool:
    return bool(re.search(r'\d', text)) or any(w in _NUMBER_WORDS for w in re.findall(r'[a-z]+', text.lower()))


def compare(primary: list[dict], other: list[dict]) -> dict:
    """{'agreement': share of matching words, 'differences': [{'start', 'end', 'text', 'other', 'numbers'}]}.
    Times and 'text' come from the primary transcript, 'other' from the second model."""
    a, a_at, a_words, ta = _words(primary)
    b, b_at, b_words, tb = _words(other)
    if not a and not b:
        return {'agreement': 1.0, 'differences': []}
    ops = _align(a, ta, b, tb)
    places, equal = [], 0      # [i1, i2, j1, j2] spans of words that differ
    since = MERGE_GAP + 1      # equal words since the last difference
    for how, i, j in ops:
        if how == 'equal':
            equal += 1
            since += 1
            continue
        i2, j2 = i + (how != 'insert'), j + (how != 'delete')
        if places and since <= MERGE_GAP:
            places[-1][1], places[-1][3] = max(places[-1][1], i2), max(places[-1][3], j2)
        else:
            places.append([i, i2, j, j2])
        since = 0
    out = []
    for i1, i2, j1, j2 in places:
        if ''.join(a[i1:i2]) == ''.join(b[j1:j2]):
            continue      # only spacing differs: "south-west" and "southwest"
        if i2 > i1:
            seg_from, seg_to = primary[a_at[i1][0]], primary[a_at[i2 - 1][0]]
        elif a:   # a word only the second model heard: the primary segment where it would stand
            seg_from = seg_to = primary[a_at[min(i1, len(a) - 1)][0]]
        else:
            seg_from, seg_to = other[b_at[j1][0]], other[b_at[j2 - 1][0]]
        text = ' '.join(a_words[k] for k in dict.fromkeys(a_at[x][1] for x in range(i1, i2)))
        alt = ' '.join(b_words[k] for k in dict.fromkeys(b_at[x][1] for x in range(j1, j2)))
        out.append({'start': seg_from['start'], 'end': seg_to['end'], 'text': text, 'other': alt,
                    'numbers': _has_number(text + ' ' + alt)})
        if len(out) == MAX_DIFFERENCES:
            break
    return {'agreement': round(2 * equal / (len(a) + len(b)), 3), 'differences': out}
