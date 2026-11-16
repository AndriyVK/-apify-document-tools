"""Tables on scanned images: ruled grids found from their lines, tables without rules from word positions.
Shared with the document-to-markdown Actor (src/convert.py there); keep both copies in step."""
from __future__ import annotations

import os
import re
import statistics
import subprocess
import tempfile

import numpy as np
import pytesseract
from PIL import Image, ImageFilter, ImageOps


class ConversionError(Exception):
    pass


BL_MIN_ROWS = 3

BL_MIN_COLS = 3

GRID_DARK = 170          # pixel value below which a pixel counts as ink

GRID_MIN_ROWS = 2        # data rows + header -> at least 3 horizontal lines

GRID_MIN_COLS = 2

_DIGIT_LOOKALIKE = str.maketrans({'З': '3', 'з': '3', 'О': '0', 'о': '0', 'O': '0', 'o': '0', 'l': '1', 'I': '1',
                                  '|': '1', 'б': '6', 'Б': '6'})

_NUMERO = re.compile(r'^(?:№|N[oо°º2]|М[оеo]|Ne|Nе|N)\.?$')

_CYRILLIC_LANGS = {'ukr', 'rus', 'bel', 'bul', 'srp', 'mkd'}

_LATIN_LANGS = {'eng', 'deu', 'fra', 'spa', 'ita', 'por', 'pol', 'nld', 'ces'}

_wordlists: dict[str, set[str]] = {}



def _tesseract(img: Image.Image, langs: str, psm: int, extra: str = '') -> str:
    try:
        return pytesseract.image_to_string(img, lang=langs, config=f'--psm {psm} {extra}'.strip())
    except pytesseract.TesseractError as e:
        raise ConversionError(f'OCR failed: {e}') from e


def _tesseract_data(img: Image.Image, langs: str) -> dict:
    try:
        return pytesseract.image_to_data(img, lang=langs, config='--psm 3', output_type=pytesseract.Output.DICT)
    except pytesseract.TesseractError as e:
        raise ConversionError(f'OCR failed: {e}') from e


def _find_borderless(d: dict) -> list[tuple[list[int], list[int]]]:
    words = [(d['left'][i], d['top'][i], d['left'][i] + d['width'][i], d['top'][i] + d['height'][i])
             for i, t in enumerate(d['text'])
             if d['level'][i] == 5 and re.search(r'\w', t or '') and d['height'][i] > 5]
    if len(words) < BL_MIN_ROWS * BL_MIN_COLS:
        return []
    hmed = statistics.median(w[3] - w[1] for w in words)
    rows = []   # [y_center_sum, count, words]
    for w in sorted(words, key=lambda w: (w[1] + w[3]) / 2):
        yc = (w[1] + w[3]) / 2
        if rows and abs(yc - rows[-1][0] / rows[-1][1]) < 0.6 * hmed:
            rows[-1][0] += yc
            rows[-1][1] += 1
            rows[-1][2].append(w)
        else:
            rows.append([yc, 1, [w]])
    gap = 0.9 * hmed
    lines = []
    for _, _, ws in rows:
        ws.sort()
        segs = [[ws[0][0], ws[0][2]]]
        for w in ws[1:]:
            if w[0] - segs[-1][1] > gap:
                segs.append([w[0], w[2]])
            else:
                segs[-1][1] = max(segs[-1][1], w[2])
        lines.append((min(w[1] for w in ws), max(w[3] for w in ws), segs))
    tables, run = [], []
    for ln in lines + [None]:
        if ln is not None and len(ln[2]) >= BL_MIN_COLS and (not run or ln[0] - run[-1][1] < 2.5 * hmed):
            run.append(ln)
            continue
        if len(run) >= BL_MIN_ROWS:
            tables.append(run)
        run = [ln] if ln is not None and len(ln[2]) >= BL_MIN_COLS else []
    grids = []
    for run in tables:
        spans = sorted([a, b] for _, _, segs in run for a, b in segs)
        cols = [spans[0]]
        for a, b in spans[1:]:
            if a - cols[-1][1] > 0.5 * hmed:
                cols.append([a, b])
            else:
                cols[-1][1] = max(cols[-1][1], b)
        if len(cols) < BL_MIN_COLS:
            continue
        pad = int(0.3 * hmed)
        xs = [cols[0][0] - pad] + [(a[1] + b[0]) // 2 for a, b in zip(cols, cols[1:])] + [cols[-1][1] + pad]
        ys = ([run[0][0] - pad] + [(a[1] + b[0]) // 2 for a, b in zip(run, run[1:])] + [run[-1][1] + pad])
        grids.append((ys, xs))
    return grids


def _has_rule(img: Image.Image) -> bool:
    """A long horizontal dark run (any table rule; on a page skewed by up to ~3 deg it is still >= w/12)."""
    small = np.asarray(img.resize((max(1, img.width // 2), max(1, img.height // 2)), Image.BILINEAR)) < GRID_DARK
    wide = small | np.roll(small, 1, axis=1) | np.roll(small, -1, axis=1)
    return bool(_runs(wide, max(40, small.shape[1] // 24)).any())


def _deskew(img: Image.Image) -> Image.Image:
    """Rotate by the angle (-3..3 deg, step 0.1) that makes text lines sharpest in the row profile."""
    small = img.resize((max(1, img.width // 4), max(1, img.height // 4)), Image.BILINEAR)
    best_angle, best_score = 0.0, -1.0
    for tenth in range(-30, 31):
        a = tenth / 10
        ink = np.asarray(small.rotate(a, resample=Image.BILINEAR, fillcolor=255)) < GRID_DARK
        prof = ink.sum(axis=1).astype(np.float64)
        score = float(((prof[1:] - prof[:-1]) ** 2).sum())
        if score > best_score:
            best_angle, best_score = a, score
    if abs(best_angle) < 0.15:
        return img
    straight = img.rotate(best_angle, resample=Image.BICUBIC, fillcolor=255)
    straight.info['deskew_angle'] = best_angle
    return straight


def _runs(mask: np.ndarray, length: int) -> np.ndarray:
    """Per row of a boolean mask: True where a run of >= length True values ends (window sum test)."""
    cs = np.cumsum(mask, axis=1, dtype=np.int32)
    cs = np.concatenate([np.zeros((mask.shape[0], 1), np.int32), cs], axis=1)
    return (cs[:, length:] - cs[:, :-length]) >= length


def _segments(idx: np.ndarray, gap: int = 2) -> list[tuple[int, int]]:
    """Sorted indices -> (first, last) groups of neighbours."""
    out = []
    for i in idx.tolist():
        if out and i - out[-1][1] <= gap:
            out[-1] = (out[-1][0], i)
        else:
            out.append((i, i))
    return out


def _find_grids(img: Image.Image) -> list[tuple[list[int], list[int]]]:
    """Ruled tables as (row line y's, column line x's), top to bottom. Empty when there is no full grid."""
    ink = np.asarray(img) < GRID_DARK
    h, w = ink.shape
    wide, tall = ink.copy(), ink.copy()
    for d in (1, 2):     # bridge breaks of up to 4 px in a rule
        wide |= np.roll(ink, d, axis=1) | np.roll(ink, -d, axis=1)
        tall |= np.roll(ink, d, axis=0) | np.roll(ink, -d, axis=0)
    min_h = max(80, w // 12)
    hrun = _runs(wide, min_h)
    hlines = []
    for y0, y1 in _segments(np.flatnonzero(hrun.any(axis=1))):
        if y1 - y0 > 12:     # a solid block (photo, black bar), not a rule
            continue
        xs = np.flatnonzero(hrun[y0:y1 + 1].any(axis=0))
        hlines.append(((y0 + y1) // 2, int(xs.min()), int(xs.max()) + min_h))
    grids, used = [], set()
    for i in sorted(range(len(hlines)), key=lambda k: hlines[k][1] - hlines[k][2]):   # longest rule first
        if i in used:
            continue
        y, x0, x1 = hlines[i]
        # a rule of the same table lies inside its width and spans most of it (noise can cut a rule's end)
        group = [j for j, (yy, a, b) in enumerate(hlines)
                 if j not in used and a >= x0 - 15 and b <= x1 + 15 and b - a >= 0.6 * (x1 - x0)]
        rows = sorted(hlines[j][0] for j in group)
        if len(rows) < GRID_MIN_ROWS + 1:
            continue
        top, bottom = rows[0], rows[-1]
        # column rules: ink from the top rule to the bottom one, looked for only inside the table box
        left = max(0, x0 - 15)
        box = tall[top + 3:bottom - 2, left:min(w, x1 + 15)]
        if box.shape[0] < 10:
            continue
        full = np.flatnonzero(box.mean(axis=0) >= 0.9)
        cols = [left + (c0 + c1) // 2 for c0, c1 in _segments(full) if c1 - c0 <= 12]
        if len(cols) < GRID_MIN_COLS + 1 or cols[0] > x0 + 15 or cols[-1] < x1 - 15:
            continue
        used.update(group)
        grids.append((rows, cols))
    return sorted(grids, key=lambda g: g[0][0])


def _to_straight(data: dict, img: Image.Image, straight: Image.Image) -> dict:
    """Words read on the page as scanned, with boxes moved to where they are on the straightened page: text
    outside tables keeps Tesseract's own reading (straightening resamples the image and can change a comma)."""
    angle = straight.info.get('deskew_angle', 0.0) if straight is not img else 0.0
    if not angle:
        return data
    a = np.radians(angle)
    cx, cy = img.width / 2, img.height / 2
    out = dict(data)
    out['left'], out['top'] = [], []
    for x, y, w, h in zip(data['left'], data['top'], data['width'], data['height']):
        xc, yc = x + w / 2 - cx, y + h / 2 - cy
        nx, ny = cx + xc * np.cos(a) + yc * np.sin(a), cy - xc * np.sin(a) + yc * np.cos(a)
        out['left'].append(int(nx - w / 2))
        out['top'].append(int(ny - h / 2))
    return out


def _read_sheet(cells: list[Image.Image], langs: str) -> list[tuple[str, bool]]:
    """Cells in one Tesseract call: a sheet of cells one under another (a call per cell is ~30 times slower).
    Per cell: its text and whether it looks misread (stray marks, a lone letter, letters in a number)."""
    pads = [ImageOps.expand(c, border=20, fill=255) for c in cells]
    sheet = Image.new('L', (max(p.width for p in pads), sum(p.height + 30 for p in pads)), 255)
    spans, y = [], 0
    for p in pads:
        sheet.paste(p, (0, y))
        spans.append((y, y + p.height))
        y += p.height + 30
    try:
        d = pytesseract.image_to_data(sheet, lang=langs, config='--psm 6 -c preserve_interword_spaces=1',
                                      output_type=pytesseract.Output.DICT)
    except pytesseract.TesseractError as e:
        raise ConversionError(f'OCR failed: {e}') from e
    words = [[] for _ in cells]
    for i, t in enumerate(d['text']):
        if d['level'][i] != 5 or not t.strip():
            continue
        yc = d['top'][i] + d['height'][i] / 2
        k = next((n for n, (a, b) in enumerate(spans) if a <= yc < b), None)
        if k is not None:
            words[k].append((d['left'][i], t.strip()))
    out = []
    for ws in words:
        ws.sort()
        kept = [t for _, t in ws if re.search(r'[^\W_]', t)]
        text = ' '.join(kept).strip(' |_:;`\'"(')
        bad = (len(kept) != len(ws) or (len(text) == 1 and not text.isdigit())
               or bool(re.search(r'\d', text) and re.search(r'[^\d\s.,\-]', text)
                       and not re.search(r'[^\W\d_]{2}', text))
               or bool(re.search(r'\d[.,;:]$|^[^\w-]|^\d{4,}(?:[.,]\d+)?$', text)))   # '2500': gap lost?
        out.append((text, bad))
    return out


def _read_table(crops, langs: str) -> list[list[str]]:
    """All cells in one call; cells that look misread are read again in one call with scan specks filtered
    out, and only those still in doubt one by one."""
    flat = [c for row in crops for c in row]
    first = _read_sheet(flat, langs)
    texts = [t for t, _ in first]
    doubt = [k for k, (_, bad) in enumerate(first) if bad]
    if doubt:
        again = _read_sheet([flat[k].filter(ImageFilter.MedianFilter(3)) for k in doubt], langs)
        still = []
        for k, (text, bad) in zip(doubt, again):
            old = texts[k]
            same = re.sub(r'\s', '', text) == re.sub(r'\s', '', old)
            if text and (not bad or (same and text.count(' ') > old.count(' '))):
                texts[k] = text
            else:
                still.append(k)
        for k in still[:6]:   # rare: a few cells at most
            texts[k] = _read_cell(flat[k], langs) or texts[k]
    n = len(crops[0])
    table = [texts[r * n:(r + 1) * n] for r in range(len(crops))]
    _even_thousands(table, crops, langs)
    for r, row in enumerate(table):
        for c, cell in enumerate(row):
            row[c] = _gap_thousands(crops[r][c], cell)
    _cyrillic_cells(table, crops, langs)
    return table


def _read_cell(cell: Image.Image, langs: str) -> str:
    """A cell as one text line. Scan specks read as stray marks ('З -'): read again with specks filtered out
    (not always: the filter can close the thousands gap in '2 500')."""
    def read(im):
        raw = _tesseract(ImageOps.expand(im, border=20, fill=255), langs, 7, '-c preserve_interword_spaces=1')
        return re.sub(r'\s+', ' ', raw).strip(), _clean_cell(raw)
    raw, text = read(cell)
    if raw != text or (len(text) == 1 and not text.isdigit()):
        _, again = read(cell.filter(ImageFilter.MedianFilter(3)))
        if again and re.sub(r'\s', '', again) != re.sub(r'\s', '', text):
            return again
        if again and again.count(' ') > text.count(' '):   # same characters: keep the reading with the gaps
            return again
    return text


def _cyrillic_cells(table, crops, langs: str) -> None:
    """With Latin and Cyrillic languages together, a short cell of a Cyrillic table is often read as Latin
    ('шт.' -> 'LUT.', 'М500' -> 'M500'). Such a cell is read again with the Cyrillic languages only and the new
    reading is kept when its words are words of those languages."""
    parts = langs.split('+')
    cyr = [x for x in parts if x in _CYRILLIC_LANGS]
    if not cyr or not set(parts) & _LATIN_LANGS:
        return
    text = ' '.join(c for r in table for c in r)
    n_cyr, n_lat = len(re.findall(r'[\u0400-\u04ff]', text)), len(re.findall(r'[A-Za-z]', text))
    if n_cyr < 1.5 * n_lat:
        return
    words = [_wordlist(x) for x in cyr]
    latin = [(r, c) for r, row in enumerate(table) for c, cell in enumerate(row) if re.search(r'[A-Za-z]', cell)]
    if not latin:
        return
    for (r, c), (again, _) in zip(latin, _read_sheet([crops[r][c] for r, c in latin], '+'.join(cyr))):
        letters = [re.sub(r'[^\w]|\d|_', '', w).lower() for w in again.split()]
        if again and not re.search(r'[A-Za-z]', again) and all(
                not w or any(w in d for d in words) for w in letters):
            table[r][c] = again


def _clean_cell(text: str) -> str:
    """One cell read as a line: parts after a wide gap that hold no letter or digit are scan specks."""
    parts = [p for p in re.split(r'\s{3,}', text.strip()) if re.search(r'\w', p)]
    tokens = re.sub(r'\s+', ' ', ' '.join(parts)).split()
    while tokens and not re.search(r'\w', tokens[0]):    # stray marks at the edges: '- (', '|'
        tokens.pop(0)
    while tokens and not re.search(r'\w', tokens[-1]):
        tokens.pop()
    return ' '.join(tokens).strip(' |_:;`\'"(')


def _fix_columns(table: list[list[str]]) -> list[list[str]]:
    """In a column of numbers, letters that look like digits are digits ('З' -> '3'); its header read as
    'Мо' / 'No' is the number sign '№'."""
    if len(table) < 3:
        return table
    width = max(len(r) for r in table)
    for c in range(width):
        cells = [r[c] for r in table[1:] if c < len(r) and r[c]]
        numeric = [x for x in cells if re.fullmatch(r'[\d\s.,\-]+', x)]
        if not cells or len(numeric) * 2 < len(cells):
            continue
        for r in table[1:]:
            if c < len(r) and r[c]:
                r[c] = re.sub(r'^[^\w\-]+|[^\w]+$', '', r[c]) or r[c]   # '412,00.' -> '412,00'
            if c < len(r) and r[c] and r[c] not in numeric:
                fixed = r[c].translate(_DIGIT_LOOKALIKE)
                if re.fullmatch(r'[\d\s.,\-]+', fixed) and re.search(r'\d', r[c]):
                    r[c] = fixed
                elif re.fullmatch(r'[\d\s.,\-]+', fixed) and len(r[c]) <= 2:
                    r[c] = fixed
        if c < len(table[0]) and _NUMERO.match(table[0][c]) and all(re.fullmatch(r'\d+', x) for x in
                                                                     (r[c] for r in table[1:] if c < len(r) and r[c])):
            table[0][c] = '№'
    return table


def table_to_markdown(rows) -> str:
    width = max(len(r) for r in rows)
    clean = [[_cell(c) for c in list(r) + [''] * (width - len(r))] for r in rows]
    lines = ['| ' + ' | '.join(clean[0]) + ' |', '| ' + ' | '.join(['---'] * width) + ' |']
    lines += ['| ' + ' | '.join(r) + ' |' for r in clean[1:]]
    return '\n'.join(lines)


def _cell(c) -> str:
    return re.sub(r'\s+', ' ', str(c or '')).replace('|', '\\|').strip()


def _wordlist(lang: str) -> set[str]:
    """Words of Tesseract's dictionary for a language (lower case), read once from its traineddata."""
    if lang in _wordlists:
        return _wordlists[lang]
    words: set[str] = set()
    try:
        tessdata = os.environ.get('TESSDATA_PREFIX') or _tessdata_dir()
        src = os.path.join(tessdata, f'{lang}.traineddata')
        with tempfile.TemporaryDirectory() as tmp:
            base = os.path.join(tmp, lang)
            subprocess.run(['combine_tessdata', '-e', src, base + '.lstm-word-dawg', base + '.lstm-unicharset'],
                           capture_output=True, timeout=60, check=True)
            subprocess.run(['dawg2wordlist', base + '.lstm-unicharset', base + '.lstm-word-dawg', base + '.txt'],
                           capture_output=True, timeout=120, check=True)
            with open(base + '.txt', encoding='utf-8') as f:
                words = {w.strip().lower() for w in f if w.strip()}
    except Exception:  # noqa: BLE001 - no dictionary means no correction, never a failed conversion
        words = set()
    _wordlists[lang] = words
    return words


def _tessdata_dir() -> str:
    out = subprocess.run(['tesseract', '--list-langs'], capture_output=True, text=True, timeout=30)
    m = re.search(r'"([^"]+)"', out.stdout + out.stderr)
    return m.group(1) if m else '/usr/share/tesseract-ocr/5/tessdata'


_GROUPED = re.compile(r'\d{1,3}(?:([ .,])\d{3})+(?:([.,])\d+)?')


def _even_thousands(table, crops, langs: str) -> None:
    """In a column where numbers group thousands with a space ('74 160,00'), a number grouped with a dot
    ('40.530,00') is most likely a misread gap: read again, and when the digits stay the same, group it like
    the rest of the column. A column that really uses dots is left alone."""
    for c in range(len(table[0])):
        styles = {}
        for r in range(1, len(table)):
            m = _GROUPED.fullmatch(table[r][c]) if c < len(table[r]) else None
            if m:
                styles[r] = (m.group(1), m.group(2))
        if len(styles) < 3:
            continue
        seps = [g for g, _ in styles.values()]
        main = max(set(seps), key=seps.count)
        if main != ' ' or seps.count(main) * 2 <= len(seps):
            continue
        for r, (g, dec) in styles.items():
            if g == main or g == dec:
                continue
            old = table[r][c]
            again = _read_cell(crops[r][c].filter(ImageFilter.MedianFilter(3)), langs)
            same = re.sub(r'\D', '', again) == re.sub(r'\D', '', old)
            if same and _GROUPED.fullmatch(again) and _GROUPED.fullmatch(again).group(1) == main:
                table[r][c] = again
            else:
                head, _, tail = old.rpartition(dec) if dec else (old, '', '')
                table[r][c] = head.replace(g, main) + (dec + tail if dec else '')


def _gap_thousands(cell: Image.Image, text: str) -> str:
    """'2500' where the image shows '2 500': Tesseract can drop a narrow thousands gap. The glyphs are measured:
    when every thousands boundary is a gap at least twice as wide as the gaps between the other characters,
    the spaces go back. Anything that does not split into exactly one glyph per character stays as read."""
    m = re.fullmatch(r'(\d{4,})([.,]\d+)?', text)
    if not m:
        return text
    ink = (np.asarray(cell.filter(ImageFilter.MedianFilter(3))) < 140).any(axis=0)
    runs, x = [], 0
    while x < len(ink):
        if ink[x]:
            start = x
            while x < len(ink) and ink[x]:
                x += 1
            runs.append((start, x))
        else:
            x += 1
    if len(runs) != len(text):
        return text
    gaps = [b[0] - a[1] for a, b in zip(runs, runs[1:])]
    n = len(m.group(1))
    marks = [i for i in range(1, n) if (n - i) % 3 == 0]          # gap before digit i starts a group
    others = [g for i, g in enumerate(gaps, 1) if i not in marks]
    if not others:
        return text
    usual = statistics.median(others)
    if all(gaps[i - 1] >= max(2 * usual, usual + 6) for i in marks):
        digits = m.group(1)
        grouped = ''.join((' ' if i in marks else '') + ch for i, ch in enumerate(digits))
        return grouped + (m.group(2) or '')
    return text
