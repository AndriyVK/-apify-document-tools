"""OCR of images and scanned PDF pages with Tesseract: text, lines and words with confidence and boxes."""
from __future__ import annotations

import os
import re
from typing import Iterator

import pypdfium2 as pdfium
import pytesseract
from PIL import Image, ImageOps, UnidentifiedImageError

from . import tables as tb

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:  # HEIC support is optional for local runs
    pass

Image.MAX_IMAGE_PIXELS = 200_000_000
PDF_DPI = 300
MIN_SIDE = 600  # small images are upscaled 2x; upscaling normal-size scans makes results worse
PSM = {'auto': 3, 'single-block': 6, 'single-line': 7, 'sparse': 11}
# Tesseract's OpenMP threads only fight over the fraction of a core an Actor gets
os.environ.setdefault('OMP_THREAD_LIMIT', '1')


class OcrError(Exception):
    pass


def detect_kind(path: str) -> str:
    with open(path, 'rb') as f:
        head = f.read(16)
    if head.startswith(b'%PDF'):
        return 'pdf'
    try:
        with Image.open(path) as im:
            im.verify()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as e:
        raise OcrError('the file is not a supported image or PDF') from e
    return 'image'


def parse_pages(spec: str, total: int) -> list[int]:
    """'1-3,5,8-' -> zero-based page indexes. Empty = all."""
    spec = (spec or '').replace(' ', '')
    if not spec:
        return list(range(total))
    out = []
    for part in spec.split(','):
        m = re.fullmatch(r'(\d*)-(\d*)|(\d+)', part)
        if not m:
            raise OcrError(f'bad page range "{part}"')
        if m.group(3):
            a = b = int(m.group(3))
        else:
            a, b = int(m.group(1) or 1), int(m.group(2) or total)
        out.extend(i - 1 for i in range(max(a, 1), min(b, total) + 1) if i - 1 not in out)
    return out


def iter_pages(path: str, kind: str, pages: str, limit: int | None) -> Iterator[tuple[int, int, Image.Image]]:
    """Yields (page number from 1, total pages, image)."""
    if kind == 'pdf':
        try:
            pdf = pdfium.PdfDocument(path)
        except pdfium.PdfiumError as e:
            raise OcrError('the PDF is damaged or password-protected') from e
        try:
            total = len(pdf)
            for n, i in enumerate(parse_pages(pages, total)):
                if limit is not None and n >= limit:
                    return
                yield i + 1, total, pdf[i].render(scale=PDF_DPI / 72).to_pil()
        finally:
            pdf.close()
        return
    with Image.open(path) as im:
        total = getattr(im, 'n_frames', 1)
        for n, i in enumerate(parse_pages(pages, total)):
            if limit is not None and n >= limit:
                return
            im.seek(i)
            yield i + 1, total, ImageOps.exif_transpose(im.copy())


def prepare(img: Image.Image) -> Image.Image:
    if img.mode in ('RGBA', 'LA', 'P'):
        bg = Image.new('RGB', img.size, 'white')
        rgba = img.convert('RGBA')
        bg.paste(rgba, mask=rgba.split()[-1])
        img = bg
    img = img.convert('L')
    if min(img.size) < MIN_SIDE:
        img = img.resize((img.width * 2, img.height * 2), Image.LANCZOS)
    return img


def rotate_upright(img: Image.Image) -> tuple[Image.Image, int]:
    try:
        osd = pytesseract.image_to_osd(img, output_type=pytesseract.Output.DICT)
    except pytesseract.TesseractError:
        return img, 0  # too little text to detect orientation
    angle = int(osd.get('rotate', 0))
    return (img.rotate(-angle, expand=True) if angle else img), angle


def _tess_data(img: Image.Image, langs: str, psm: str) -> dict:
    try:
        return pytesseract.image_to_data(img, lang=langs, config=f'--psm {PSM.get(psm, 3)}',
                                         output_type=pytesseract.Output.DICT)
    except pytesseract.TesseractError as e:
        raise OcrError(f'OCR failed: {str(e)[:200]}') from e


# Ukrainian and Russian together: Tesseract leans on the first language of the list, so Russian read with
# Ukrainian first loses 'ы' and 'ё' ('строительньх', 'Отчет') and Ukrainian read with Russian first loses 'і'.
# Letters only one of them has tell which language a page is in.
_UK_ONLY, _RU_ONLY = set('іїєґІЇЄҐ'), set('ыэъёЫЭЪЁ')


def _page_lang_order(text: str, langs: str) -> str | None:
    """Languages reordered with the page's own language first, or None when the order is fine."""
    parts = langs.split('+')
    if 'ukr' not in parts or 'rus' not in parts:
        return None
    letters = re.findall(r'[\u0400-\u04ff]', text)
    if len(letters) < 60:
        return None
    uk, ru = sum(c in _UK_ONLY for c in letters), sum(c in _RU_ONLY for c in letters)
    first = next(x for x in parts if x in ('ukr', 'rus'))
    want = 'rus' if first == 'ukr' and uk == 0 and ru >= 0 else 'ukr' if first == 'rus' and ru == 0 and uk >= 0 else None
    if want is None or want == first:
        return None
    return '+'.join([want] + [x for x in parts if x != want])


def _words_text(data: dict) -> str:
    return ' '.join(t for t in data['text'] if t and t.strip())


def _numero(text: str, langs: str) -> str:
    """'№' read by Tesseract as 'Мо' / 'Ме' / 'Ne' before a number (Cyrillic languages)."""
    if not set(langs.split('+')) & tb._CYRILLIC_LANGS:
        return text
    return re.sub(r'(?<![^\W\d_])(?:Мо|Ме|Мe|Mo|Ne|Nе|М»|М°|N°)(?=\s*\d)', '№', text)


def _find_tables(prepared: Image.Image, data: dict, langs: str):
    """(straightened image, grids, page words moved onto it) or None. Ruled grids first, then tables without rules."""
    try:
        if tb._has_rule(prepared):
            straight = tb._deskew(prepared)
            grids = tb._find_grids(straight)
            if grids:
                return straight, grids, tb._to_straight(data, prepared, straight)
        if tb._find_borderless(data):
            straight = tb._deskew(prepared)
            moved = tb._to_straight(data, prepared, straight)   # words as Tesseract split them on the page as scanned
            grids = tb._find_borderless(moved)
            if grids:
                return straight, grids, moved
    except Exception:  # noqa: BLE001 - tables are an extra: on any failure the page keeps its plain text
        return None
    return None


def ocr(img: Image.Image, langs: str, psm: str = 'auto', words: bool = False, find_tables: bool = True) -> dict:
    scale = 1.0
    prepared = prepare(img)
    if prepared.width != img.width:
        scale = img.width / prepared.width
    data = _tess_data(prepared, langs, psm)
    reordered = _page_lang_order(_words_text(data), langs)
    if reordered:   # one more pass with the page's own language first
        data = _tess_data(prepared, reordered, psm)
        langs = reordered
    found = _find_tables(prepared, data, langs) if find_tables and psm in ('auto', 'single-block') else None
    table_rows, boxes = [], []
    if found:
        straight, grids, moved = found
        try:
            for rows, cols in grids:
                crops = [[straight.crop((c0 + 5, r0 + 5, c1 - 4, r1 - 4)) for c0, c1 in zip(cols, cols[1:])]
                         for r0, r1 in zip(rows, rows[1:])]
                t = tb._fix_columns(tb._read_table(crops, langs))
                if any(any(c for c in r) for r in t):
                    table_rows.append(t)
                    boxes.append((cols[0], rows[0], cols[-1], rows[-1]))
        except tb.ConversionError as e:
            raise OcrError(f'OCR failed: {str(e)[:200]}') from e
    else:
        moved = None
    lines, word_list, blocks = {}, [], []
    for i, text in enumerate(data['text']):
        text = (text or '').strip()
        conf = float(data['conf'][i])
        if not text or conf < 0:
            continue
        box = [round(v * scale) for v in (data['left'][i], data['top'][i], data['width'][i], data['height'][i])]
        key = (data['block_num'][i], data['par_num'][i], data['line_num'][i])
        seg = len(boxes)   # text before table k, or after the last one
        if moved is not None:
            xc = moved['left'][i] + data['width'][i] / 2
            yc = moved['top'][i] + data['height'][i] / 2
            if any(x0 <= xc <= x1 and y0 <= yc <= y1 for x0, y0, x1, y1 in boxes):
                key = None   # inside a table: the table's own cells replace these words in text
            else:
                seg = next((k for k, (x0, y0, x1, y1) in enumerate(boxes) if yc <= y1), len(boxes))
        if key is None:
            if words:
                word_list.append({'text': text, 'confidence': round(conf, 1), 'bbox': box})
            continue
        line = lines.setdefault(key, {'words': [], 'confs': [], 'boxes': [], 'seg': seg})
        line['words'].append(text)
        line['confs'].append(conf)
        line['boxes'].append(box)
        if words:
            word_list.append({'text': text, 'confidence': round(conf, 1), 'bbox': box})
    out_lines, paragraphs, last_par = [], [], None
    segs: list[list] = [[] for _ in range(len(boxes) + 1)]
    for key in sorted(lines):
        line = lines[key]
        x0 = min(b[0] for b in line['boxes'])
        y0 = min(b[1] for b in line['boxes'])
        x1 = max(b[0] + b[2] for b in line['boxes'])
        y1 = max(b[1] + b[3] for b in line['boxes'])
        text = ' '.join(line['words'])
        out_lines.append({'text': text, 'confidence': round(sum(line['confs']) / len(line['confs']), 1),
                          'bbox': [x0, y0, x1 - x0, y1 - y0]})
        if key[:2] != last_par or not segs[line['seg']]:
            segs[line['seg']].append([])
            last_par = key[:2]
        segs[line['seg']][-1].append(_numero(text, langs))
    all_confs = [c for line in lines.values() for c in line['confs']]
    text_parts, md_parts = [], []
    for k, paras in enumerate(segs):
        chunk = '\n\n'.join('\n'.join(p) for p in paras if p)
        if chunk:
            text_parts.append(chunk)
            md_parts.append(chunk)
        if k < len(table_rows):
            text_parts.append('\n'.join('\t'.join(r) for r in table_rows[k]))   # one table row per line
            md_parts.append(tb.table_to_markdown(table_rows[k]))
    result = {
        'text': '\n\n'.join(text_parts),
        'meanConfidence': round(sum(all_confs) / len(all_confs), 1) if all_confs else None,
        'lines': out_lines,
        'width': img.width,
        'height': img.height,
    }
    if table_rows:
        result['tables'] = table_rows
        result['markdown'] = '\n\n'.join(md_parts)
    if reordered:
        result['languagesUsed'] = reordered.split('+')
    if words:
        result['words'] = word_list
    return result
