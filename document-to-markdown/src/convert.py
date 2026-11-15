"""Document -> Markdown conversion core (no Apify dependencies, testable locally).

PDF: pdfplumber text and tables, headings from font size; pages without a text layer go to Tesseract OCR.
Office/HTML/text: markitdown. Legacy formats (doc, xls, ppt, odt, rtf, ...): LibreOffice first.
Images: Tesseract OCR.
"""
from __future__ import annotations

import os
import re
import shutil
import statistics
import subprocess
import tempfile
from dataclasses import dataclass, field

import numpy as np
import pdfplumber
import pypdfium2 as pdfium
import pytesseract
from PIL import Image, ImageFilter, ImageOps

PDF_EXT = {'.pdf'}
IMAGE_EXT = {'.png', '.jpg', '.jpeg', '.tif', '.tiff', '.bmp', '.webp', '.gif'}
SHEET_EXT = {'.xlsx', '.xlsm'}
MARKITDOWN_EXT = {'.docx', '.pptx', '.html', '.htm', '.csv', '.json', '.xml', '.txt', '.md', '.epub'}
# Converted by LibreOffice first. Word-family files go through XHTML: its DOCX output loses tables for markitdown
LIBREOFFICE_TARGET = {
    '.doc': ('html:XHTML Writer File:UTF8', '.html'), '.odt': ('html:XHTML Writer File:UTF8', '.html'),
    '.rtf': ('html:XHTML Writer File:UTF8', '.html'), '.wpd': ('html:XHTML Writer File:UTF8', '.html'),
    '.dot': ('html:XHTML Writer File:UTF8', '.html'), '.dotx': ('html:XHTML Writer File:UTF8', '.html'),
    '.docm': ('html:XHTML Writer File:UTF8', '.html'),
    '.xls': ('xlsx', '.xlsx'), '.ods': ('xlsx', '.xlsx'), '.xlsb': ('xlsx', '.xlsx'),
    '.ppt': ('pptx', '.pptx'), '.odp': ('pptx', '.pptx'), '.pps': ('pptx', '.pptx'), '.ppsx': ('pptx', '.pptx'),
    '.pptm': ('pptx', '.pptx'),
}
SUPPORTED_EXT = PDF_EXT | IMAGE_EXT | SHEET_EXT | MARKITDOWN_EXT | set(LIBREOFFICE_TARGET)

# A page with fewer extracted characters than this is treated as a scan
MIN_TEXT_CHARS = 25
OCR_DPI = 300
# Tesseract's OpenMP threads only fight over the fraction of a core an Actor gets: ~25% slower than one thread
os.environ.setdefault('OMP_THREAD_LIMIT', '1')
# For non-paginated formats one billable page = this many characters of output (min 1)
CHARS_PER_PAGE = 3000


class ConversionError(Exception):
    pass


@dataclass
class Result:
    markdown: str = ''
    page_count: int = 0          # billable text pages
    ocr_pages: int = 0           # billable OCR pages
    source_pages: int | None = None
    metadata: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def detect_ext(path: str, name_hint: str = '', content_type: str = '') -> str:
    """Extension from the file name or, failing that, from magic bytes / content type."""
    for candidate in (name_hint, path):
        ext = os.path.splitext(candidate.split('?')[0])[1].lower()
        if ext in SUPPORTED_EXT:
            return ext
    with open(path, 'rb') as f:
        head = f.read(8)
    if head.startswith(b'%PDF'):
        return '.pdf'
    if head.startswith(b'\x89PNG'):
        return '.png'
    if head.startswith(b'\xff\xd8'):
        return '.jpg'
    if head[:4] in (b'II*\x00', b'MM\x00*'):
        return '.tiff'
    if head.startswith(b'{\\rtf'):
        return '.rtf'
    ct = content_type.split(';')[0].strip().lower()
    by_type = {
        'application/pdf': '.pdf', 'text/html': '.html', 'text/plain': '.txt', 'text/csv': '.csv',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '.docx',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': '.xlsx',
        'application/vnd.openxmlformats-officedocument.presentationml.presentation': '.pptx',
        'application/msword': '.doc', 'application/vnd.ms-excel': '.xls', 'application/vnd.ms-powerpoint': '.ppt',
        'application/vnd.oasis.opendocument.text': '.odt', 'application/rtf': '.rtf',
    }
    if ct in by_type:
        return by_type[ct]
    if head.startswith(b'PK'):
        return '.docx'  # unknown zip container: markitdown sniffs the actual type
    raise ConversionError(f'unsupported file type (name {name_hint!r}, content type {content_type!r})')


ZIP_EXT = {'.docx', '.docm', '.dotx', '.xlsx', '.xlsm', '.xlsb', '.pptx', '.pptm', '.ppsx', '.odt', '.ods', '.odp',
           '.epub'}
OLE_EXT = {'.doc', '.dot', '.xls', '.ppt', '.pps'}


def check_signature(path: str, ext: str) -> None:
    """LibreOffice and markitdown read unreadable binaries as plain text; refuse them instead of charging for junk."""
    with open(path, 'rb') as f:
        head = f.read(1024)
    if ((ext in ZIP_EXT and not head.startswith(b'PK'))
            or (ext in OLE_EXT and not head.startswith((b'\xd0\xcf\x11\xe0', b'PK')))
            or (ext == '.rtf' and not head.startswith(b'{\\rtf'))
            or (ext == '.pdf' and b'%PDF' not in head)):  # a PDF header may follow a little junk
        raise ConversionError(f'not a valid {ext} file (damaged or wrong extension)')


def convert(path: str, ext: str, *, ocr_mode: str = 'auto', ocr_languages: str = 'eng',
            max_pages: int = 500, page_budget=None) -> Result:
    """page_budget(text_pages, ocr_pages) -> bool lets the caller stop before work it cannot charge for."""
    check_signature(path, ext)
    if ext in PDF_EXT:
        return _convert_pdf(path, ocr_mode, ocr_languages, max_pages, page_budget)
    if ext in IMAGE_EXT:
        return _convert_image(path, ocr_languages, max_pages)
    if ext in LIBREOFFICE_TARGET:
        target, new_ext = LIBREOFFICE_TARGET[ext]
        with tempfile.TemporaryDirectory() as tmp:
            converted = _libreoffice(path, target, new_ext, tmp)
            return _convert_sheet(converted) if new_ext in SHEET_EXT else _convert_markitdown(converted)
    if ext in SHEET_EXT:
        return _convert_sheet(path)
    return _convert_markitdown(path)


# ---------------------------------------------------------------- PDF

def _convert_pdf(path, ocr_mode, langs, max_pages, page_budget) -> Result:
    res = Result()
    try:
        pdf = pdfplumber.open(path)
    except Exception as e:  # noqa: BLE001 - pdfminer raises many exception types
        raise ConversionError(f'cannot open PDF: {e}') from e
    with pdf:
        res.source_pages = len(pdf.pages)
        info = pdf.metadata or {}
        res.metadata = {k.lower(): str(v) for k, v in info.items() if k in ('Title', 'Author', 'Subject', 'CreationDate') and v}
        pages = pdf.pages[:max_pages]
        if len(pdf.pages) > max_pages:
            res.warnings.append(f'only the first {max_pages} of {len(pdf.pages)} pages were converted')
        body_size = _body_font_size(pages)
        parts = []
        doc = None
        for n, page in enumerate(pages, 1):
            text_md = '' if ocr_mode == 'always' else _pdf_page_markdown(page, body_size)
            need_ocr = ocr_mode == 'always' or (ocr_mode == 'auto' and _looks_scanned(page, text_md))
            if page_budget and not page_budget(0 if need_ocr else 1, 1 if need_ocr else 0):
                res.warnings.append(f'stopped at page {n}: maximum charge per run reached')
                break
            if need_ocr:
                if doc is None:
                    doc = pdfium.PdfDocument(path)
                img = doc[n - 1].render(scale=OCR_DPI / 72).to_pil()
                text_md = _ocr_image(img, langs)
                res.ocr_pages += 1
            else:
                res.page_count += 1
            if text_md.strip():
                parts.append(text_md.strip())
        if doc is not None:
            doc.close()
    res.markdown = '\n\n'.join(parts) + '\n'
    return res


def _looks_scanned(page, text_md: str) -> bool:
    """No text layer at all, or only a few characters on top of a page-sized image (scanner stamp, OCR'd title)."""
    if not page.chars:  # blank pages stay cheap text pages; text drawn as curves needs OCR
        return bool(page.images) or len(page.curves) + len(page.lines) > 20
    if len(text_md.strip()) >= MIN_TEXT_CHARS:
        return False
    page_area = float(page.width * page.height) or 1.0
    return any(float((im['x1'] - im['x0']) * (im['bottom'] - im['top'])) > 0.5 * page_area for im in page.images)


def _body_font_size(pages) -> float:
    sizes = []
    for page in pages[:20]:
        sizes.extend(round(c['size'], 1) for c in page.chars[:4000])
    return statistics.median(sizes) if sizes else 10.0


def _pdf_page_markdown(page, body_size: float) -> str:
    """Text regions between tables (top to bottom) with tables rendered as Markdown."""
    try:
        tables = sorted(page.find_tables(), key=lambda t: t.bbox[1])
    except Exception:  # noqa: BLE001
        tables = []
    out, top = [], 0
    for t in tables:
        x0, t_top, x1, t_bottom = t.bbox
        if t_top > top:
            out.append(_region_text(page, top, t_top, body_size))
        rows = t.extract()
        if rows and len(rows) >= 2 and max(len(r) for r in rows) >= 2:
            out.append(table_to_markdown(rows))
        else:  # one-cell "table" (a frame around text): keep it as text
            out.append(_region_text(page, t_top, t_bottom, body_size))
        top = max(top, t_bottom)
    if top < page.height:
        out.append(_region_text(page, top, page.height, body_size))
    return '\n\n'.join(p for p in out if p.strip())


BULLET = re.compile(r'^[•●▪◦\-–*]\s+')
NUMBERED = re.compile(r'^(\d{1,3})[.)]\s+')


def _region_text(page, top, bottom, body_size) -> str:
    bottom = min(bottom, page.height)
    if bottom - top < 1:
        return ''
    region = page.crop((0, max(0, top), page.width, bottom), strict=False)
    lines = region.extract_text_lines(return_chars=True, strip=True)
    md, para = [], []

    def flush():
        if para:
            md.append(' '.join(para))
            para.clear()

    for ln in lines:
        text = ln['text'].strip()
        if not text:
            continue
        size = statistics.median(c['size'] for c in ln['chars']) if ln['chars'] else body_size
        if size >= body_size * 1.45 and len(text) < 120:
            flush()
            md.append('# ' + text)
        elif size >= body_size * 1.15 and len(text) < 120:
            flush()
            md.append('## ' + text)
        elif BULLET.match(text):
            flush()
            md.append('- ' + BULLET.sub('', text))
        elif NUMBERED.match(text):
            flush()
            md.append(NUMBERED.sub(r'\1. ', text))
        else:
            para.append(text)
    flush()
    return '\n\n'.join(md)


def table_to_markdown(rows) -> str:
    width = max(len(r) for r in rows)
    clean = [[_cell(c) for c in list(r) + [''] * (width - len(r))] for r in rows]
    lines = ['| ' + ' | '.join(clean[0]) + ' |', '| ' + ' | '.join(['---'] * width) + ' |']
    lines += ['| ' + ' | '.join(r) + ' |' for r in clean[1:]]
    return '\n'.join(lines)


def _cell(c) -> str:
    return re.sub(r'\s+', ' ', str(c or '')).replace('|', '\\|').strip()


# ---------------------------------------------------------------- OCR

def _ocr_image(img: Image.Image, langs: str) -> str:
    img = ImageOps.exif_transpose(img).convert('L')
    grids = []
    try:
        if _has_rule(img):   # straightening costs ~0.5 s a page: only where a table may be
            straight = _deskew(img)
            grids = _find_grids(straight)
    except Exception:  # noqa: BLE001 - table search is an extra: on any failure fall back to plain OCR
        grids = []
    if grids:
        return _ocr_with_grids(straight, grids, langs)
    data = _tesseract_data(img, langs)
    try:
        if _find_borderless(data):   # columns of words without rules: read again on the straightened page
            straight = _deskew(img)
            sdata = data if straight is img else _tesseract_data(straight, langs)
            grids = _find_borderless(sdata)
    except Exception:  # noqa: BLE001
        grids = []
    if grids:
        return _ocr_with_grids(straight, grids, langs, _to_straight(data, img, straight))
    return _fix_lookalikes(_ocr_layout(_data_text(data)), langs)


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


def _data_text(d: dict) -> str:
    """Words of image_to_data back to text as image_to_string lays it out: a blank line between paragraphs."""
    out, prev = [], None
    for i, t in enumerate(d['text']):
        if d['level'][i] != 5 or not t.strip():
            continue
        conf = float(d['conf'][i])
        if ((len(t.strip()) <= 2 and conf < 10) or (not re.search(r'[^\W_]', t) and conf < 60)
                or re.fullmatch(r'_+', t.strip())):
            continue   # a scan speck read as a short word, a stray mark or an underscore
        key = (d['block_num'][i], d['par_num'][i], d['line_num'][i])
        if key != prev and t.startswith('(') and ')' not in t and conf < 75 and not any(
                ')' in d['text'][j] for j in range(i + 1, len(d['text']))
                if (d['block_num'][j], d['par_num'][j], d['line_num'][j]) == key):
            t = t[1:]   # a speck before the first word read as an opening bracket that never closes
        if prev is not None:
            out.append('\n\n' if key[:2] != prev[:2] else '\n' if key != prev else ' ')
        out.append(t)
        prev = key
    return ''.join(out) + '\n'


# Tables without rules on scans: rows of words with wide gaps that line up in columns. Rows come from word
# positions (Tesseract may put one row's cells in different blocks), columns from the gaps shared by all rows.
BL_MIN_ROWS = 3
BL_MIN_COLS = 3


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


# Ruled tables on scans. Tesseract reads grid lines as '|' only on clean scans; on a noisy or skewed one the
# columns come out as separate text blocks. So the page is straightened, the grid is found from long dark
# lines, and every cell is read on its own.
GRID_DARK = 170          # pixel value below which a pixel counts as ink
GRID_MIN_ROWS = 2        # data rows + header -> at least 3 horizontal lines
GRID_MIN_COLS = 2


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


def _ocr_with_grids(img: Image.Image, grids, langs: str, data: dict | None = None) -> str:
    """Text above, beside and below each table from one OCR pass of the page; tables cell by cell."""
    if data is None:
        data = _tesseract_data(img, langs)
    boxes = [(cols[0], rows[0], cols[-1], rows[-1]) for rows, cols in grids]
    segments = [[] for _ in range(len(grids) + 1)]   # words before table k (above or beside it), then the rest
    for i, t in enumerate(data['text']):
        if data['level'][i] != 5 or not t.strip():
            continue
        xc, yc = data['left'][i] + data['width'][i] / 2, data['top'][i] + data['height'][i] / 2
        if any(x0 <= xc <= x1 and y0 <= yc <= y1 for x0, y0, x1, y1 in boxes):
            continue
        k = next((n for n, (x0, y0, x1, y1) in enumerate(boxes) if yc <= y1), len(grids))
        segments[k].append(i)
    blocks = []
    for k in range(len(grids) + 1):
        if segments[k]:
            text = _ocr_layout(_data_text({key: [v[i] for i in segments[k]] for key, v in data.items()}))
            if text:
                blocks.append(text)
        if k < len(grids):
            rows, cols = grids[k]
            crops = [[img.crop((c0 + 5, r0 + 5, c1 - 4, r1 - 4)) for c0, c1 in zip(cols, cols[1:])]
                     for r0, r1 in zip(rows, rows[1:])]
            table = _read_table(crops, langs)
            if any(any(c for c in r) for r in table):
                blocks.append(table_to_markdown(_fix_columns(table)))
    return _fix_lookalikes(_join_broken('\n\n'.join(blocks)), langs)


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


_DIGIT_LOOKALIKE = str.maketrans({'З': '3', 'з': '3', 'О': '0', 'о': '0', 'O': '0', 'o': '0', 'l': '1', 'I': '1',
                                  '|': '1', 'б': '6', 'Б': '6'})
_NUMERO = re.compile(r'^(?:№|N[oо°º2]|М[оеo]|Ne|Nе|N)\.?$')


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


def _table_row(line: str) -> str | None:
    """A Tesseract line read from a ruled table ('| a | b | c', borders as pipes) -> '| a | b | c |'."""
    s = line.strip()
    if s.count('|') < 2:
        return None
    cells = [c.strip() for c in s.strip('|').split('|')]
    if len(cells) < 2 or not any(cells):
        return None
    return '| ' + ' | '.join(cells) + ' |'


def _ocr_layout(text: str) -> str:
    """Join lines inside a paragraph, keep blank-line paragraph breaks; table rows stay one per line."""
    out = []
    for para in re.split(r'\n\s*\n', text):
        lines, buf = [], []
        for line in para.splitlines():
            row = _table_row(line)
            if row:
                if buf:
                    lines.append(('p', ' '.join(buf)))
                    buf = []
                lines.append(('t', row))
            elif line.strip():
                buf.append(line.strip())
        if buf:
            lines.append(('p', ' '.join(buf)))
        for kind, value in lines:
            if kind == 't' and out and out[-1][0] == 't':
                out[-1] = ('t', out[-1][1] + '\n' + value)   # rows of one table, even across a blank line
            else:
                out.append((kind, value))
    blocks = []
    for kind, value in out:
        if kind == 't':
            rows = value.split('\n')
            if len(rows) < 2:   # a lone row is usually a broken grid on a noisy scan: keep it as text
                blocks.append(' '.join(c.strip() for c in rows[0].strip('|').split('|') if c.strip()))
                continue
            value = _fix_tables('\n'.join(_even_rows(rows)))   # separator row after the header
        blocks.append(value)
    return _join_broken('\n\n'.join(b for b in blocks if b))


def _join_broken(text: str) -> str:
    """Tesseract puts a blank line between lines of one paragraph when line spacing is wide: a block that
    ends without sentence-final punctuation is joined to the next one when that one starts lowercase."""
    out = []
    for block in text.split('\n\n'):
        if (out and block and not block.startswith('|') and not out[-1].startswith('|')
                and not re.search(r'[.!?:;…»")\]]$', out[-1]) and block[0].islower()):
            out[-1] += ' ' + block
        else:
            out.append(block)
    return '\n\n'.join(out)


def _even_rows(rows: list[str]) -> list[str]:
    """Same number of cells in every row. Tesseract may read a stray grid mark as an extra '|'
    ('| Cement | 420 | | | 96.50'): when a row holds as many filled cells as the fullest row, its empty cells go."""
    cells = [[c.strip() for c in r.strip().strip('|').split('|')] for r in rows]
    width = max(sum(1 for c in row if c) for row in cells)
    out = []
    for row in cells:
        if sum(1 for c in row if c) == width:
            row = [c for c in row if c]
        row = (row + [''] * width)[:width] if len(row) != width else row
        out.append('| ' + ' | '.join(row) + ' |')
    return out


# Latin letters that look like Cyrillic ones. With e.g. 'ukr+eng' Tesseract sometimes reads a Cyrillic word as
# Latin ('Арматура' -> 'Apmatypa'); such a word is put back in Cyrillic when the Cyrillic spelling is a word of
# the Cyrillic language's Tesseract dictionary and the Latin one is not an English word.
_LOOKALIKE = str.maketrans('AaBCcEeHIiKkMmOoPpTtXxYyn', 'АаВСсЕеНІіКкМмОоРрТтХхУуп')
_CYRILLIC_LANGS = {'ukr', 'rus', 'bel', 'bul', 'srp', 'mkd'}
_LATIN_LANGS = {'eng', 'deu', 'fra', 'spa', 'ita', 'por', 'pol', 'nld', 'ces'}
_wordlists: dict[str, set[str]] = {}


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


def _fix_lookalikes(text: str, langs: str) -> str:
    parts = set(langs.split('+'))
    if parts & _CYRILLIC_LANGS:   # Tesseract reads the number sign '№' as 'Мо' / 'Ме' before a number
        text = re.sub(r'(?<![^\W\d_])(?:Мо|Ме|Мe|Mo|Ne|Nе|М»|М°|N°)(?=\s*\d)', '№', text)
    cyr = sorted(parts & _CYRILLIC_LANGS)
    if not cyr or not parts & _LATIN_LANGS:
        return text
    # whole Latin words ('Apmatypa') and mixed-script words ('Koт'); the Cyrillic spelling must be all Cyrillic
    suspects = {w for w in re.findall(r'[^\W\d_]{3,}', text)
                if re.search(r'[A-Za-z]', w) and re.fullmatch(r'[\u0400-\u04ff]+', w.translate(_LOOKALIKE))}
    if not suspects:
        return text
    english = _wordlist('eng') if 'eng' in parts else set()
    dictionaries = [_wordlist(lang) for lang in cyr]
    fixes = {}
    for w in suspects:
        cyr_word = w.translate(_LOOKALIKE)
        if (w.lower() not in english or not w.isascii()) and any(cyr_word.lower() in d for d in dictionaries):
            fixes[w] = cyr_word
    if not fixes:
        return text
    pattern = re.compile(r'(?<![^\W\d_])(' + '|'.join(map(re.escape, sorted(fixes, key=len, reverse=True)))
                         + r')(?![^\W\d_])')   # whole words only
    return pattern.sub(lambda m: fixes[m.group(1)], text)


def _convert_image(path, langs, max_pages) -> Result:
    res = Result()
    try:
        img = Image.open(path)
    except Exception as e:  # noqa: BLE001
        raise ConversionError(f'cannot open image: {e}') from e
    frames = getattr(img, 'n_frames', 1)
    res.source_pages = frames
    parts = []
    for i in range(min(frames, max_pages)):
        img.seek(i)
        parts.append(_ocr_image(img.copy(), langs))
        res.ocr_pages += 1
    if frames > max_pages:
        res.warnings.append(f'only the first {max_pages} of {frames} frames were converted')
    res.markdown = '\n\n'.join(p for p in parts if p) + '\n'
    return res


# ---------------------------------------------------------------- Office, HTML, text

_markitdown = None


def _convert_markitdown(path) -> Result:
    global _markitdown
    if _markitdown is None:
        from markitdown import MarkItDown
        _markitdown = MarkItDown(enable_plugins=False)
    try:
        out = _markitdown.convert_local(path)
    except Exception as e:  # noqa: BLE001
        raise ConversionError(f'cannot convert document: {e}') from e
    res = Result(markdown=_tidy(out.text_content or '') + '\n')
    if getattr(out, 'title', None):
        res.metadata['title'] = out.title
    res.page_count = _char_pages(res.markdown)
    return res


def _char_pages(md: str) -> int:
    return max(1, -(-len(md.strip()) // CHARS_PER_PAGE))


def _tidy(md: str) -> str:
    md = re.sub(r'<!--\s*Slide number:\s*(\d+)\s*-->', r'## Slide \1', md)
    md = re.sub(r'[]', '', md)  # Symbol-font bullet glyphs from Word files
    md = _fix_tables(md)
    md = re.sub(r'\n{3,}', '\n\n', md)
    return md.strip()


SEPARATOR = re.compile(r'^\|(\s*:?-{3,}:?\s*\|)+$')


def _fix_tables(md: str) -> str:
    """Every pipe table gets a separator row; an empty header row is replaced by the first data row."""
    out, block = [], []

    def flush():
        if block:
            rows = [r for r in block if not SEPARATOR.match(r.strip())]
            if rows and not re.sub(r'[|\s]', '', rows[0]) and len(rows) > 1:
                rows = rows[1:]
            if rows:
                ncol = rows[0].strip().count('|') - 1
                out.extend([rows[0], '| ' + ' | '.join(['---'] * max(1, ncol)) + ' |'] + rows[1:])
            block.clear()

    for line in md.splitlines():
        s = line.strip()
        if s.startswith('|') and s.endswith('|') and len(s) > 1:
            block.append(s)
        else:
            flush()
            out.append(line)
    flush()
    return '\n'.join(out)


def _convert_sheet(path) -> Result:
    """XLSX via openpyxl: text cells as written, numbers and dates by the cell's own format."""
    from openpyxl import load_workbook
    try:
        wb = load_workbook(path, read_only=True, data_only=True)
    except Exception as e:  # noqa: BLE001
        raise ConversionError(f'cannot open spreadsheet: {e}') from e
    parts = []
    for ws in wb.worksheets:
        rows = [[_sheet_value(c) for c in row] for row in ws.iter_rows()]
        rows = [r for r in rows if any(v for v in r)]
        if not rows:
            continue
        used = [j for j in range(max(len(r) for r in rows)) if any(j < len(r) and r[j] for r in rows)]
        rows = [[r[j] if j < len(r) else '' for j in used] for r in rows]
        parts.append(f'## {ws.title}\n\n' + (table_to_markdown(rows) if len(used) > 1 or len(rows) > 1
                                              else rows[0][0]))
    wb.close()
    md = '\n\n'.join(parts) + '\n'
    return Result(markdown=md, page_count=_char_pages(md))


def _sheet_value(cell) -> str:
    v = cell.value
    if v is None:
        return ''
    if isinstance(v, bool):
        return 'TRUE' if v else 'FALSE'
    if isinstance(v, (int, float)):
        fmt = (getattr(cell, 'number_format', '') or '').split(';')[0]
        m = re.search(r'0[.,](0+)', fmt)
        if m:
            s = f'{v:,.{len(m.group(1))}f}' if ',' in fmt.split('.')[0] else f'{v:.{len(m.group(1))}f}'
        elif isinstance(v, float) and v.is_integer():
            s = str(int(v))
        else:
            s = repr(v) if isinstance(v, float) else str(v)
        return s + '%' if fmt.endswith('%') and m else s
    if hasattr(v, 'isoformat'):
        s = v.isoformat()
        return s[:-9] if s.endswith('T00:00:00') else s
    return str(v)


def _libreoffice(path, target, new_ext, outdir) -> str:
    soffice = shutil.which('soffice') or shutil.which('libreoffice')
    if not soffice:
        raise ConversionError('LibreOffice is not available')
    profile = tempfile.mkdtemp(prefix='lo-profile-')
    try:
        subprocess.run([soffice, f'-env:UserInstallation=file://{profile}', '--headless', '--norestore',
                        '--convert-to', target, '--outdir', outdir, path],
                       check=True, capture_output=True, timeout=180)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        raise ConversionError(f'LibreOffice conversion failed: {e}') from e
    finally:
        shutil.rmtree(profile, ignore_errors=True)
    out = os.path.join(outdir, os.path.splitext(os.path.basename(path))[0] + new_ext)
    if not os.path.exists(out):
        raise ConversionError('LibreOffice produced no output')
    return out


# ---------------------------------------------------------------- tables and chunks from Markdown

def extract_tables(md: str) -> list[list[list[str]]]:
    """Markdown pipe tables -> list of tables (rows of cells), header row first."""
    tables, cur = [], []
    for line in md.splitlines() + ['']:
        s = line.strip()
        if s.startswith('|') and s.endswith('|') and len(s) > 1:
            cells = [c.strip().replace('\\|', '|') for c in re.split(r'(?<!\\)\|', s[1:-1])]
            if not all(re.fullmatch(r':?-{2,}:?', c) for c in cells if c):
                cur.append(cells)
        elif cur:
            if len(cur) >= 2 or (cur and len(cur[0]) >= 2):
                tables.append(cur)
            cur = []
    return tables


def chunk_markdown(md: str, size: int) -> list[dict]:
    """Split on blank lines into chunks of at most ~size characters, each carrying its nearest heading."""
    chunks, buf, buf_heading, heading = [], [], '', ''
    for block in re.split(r'\n\s*\n', md):
        block = block.strip()
        if not block:
            continue
        if block.startswith('#'):
            heading = block.lstrip('#').strip().split('\n')[0]
        for piece in (block[i:i + size] for i in range(0, len(block), size)):
            if buf and len('\n\n'.join(buf + [piece])) > size:
                chunks.append({'heading': buf_heading, 'text': '\n\n'.join(buf)})
                buf = []
            if not buf:
                buf_heading = heading
            buf.append(piece)
    if buf:
        chunks.append({'heading': buf_heading, 'text': '\n\n'.join(buf)})
    return [dict(index=i, **c) for i, c in enumerate(chunks)]
