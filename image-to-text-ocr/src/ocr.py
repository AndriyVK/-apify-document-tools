"""OCR of images and scanned PDF pages with Tesseract: text, lines and words with confidence and boxes."""
from __future__ import annotations

import re
from typing import Iterator

import pypdfium2 as pdfium
import pytesseract
from PIL import Image, ImageOps, UnidentifiedImageError

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:  # HEIC support is optional for local runs
    pass

Image.MAX_IMAGE_PIXELS = 200_000_000
PDF_DPI = 300
MIN_SIDE = 600  # small images are upscaled 2x; upscaling normal-size scans makes results worse
PSM = {'auto': 3, 'single-block': 6, 'single-line': 7, 'sparse': 11}


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


def ocr(img: Image.Image, langs: str, psm: str = 'auto', words: bool = False) -> dict:
    scale = 1.0
    prepared = prepare(img)
    if prepared.width != img.width:
        scale = img.width / prepared.width
    try:
        data = pytesseract.image_to_data(prepared, lang=langs, config=f'--psm {PSM.get(psm, 3)}',
                                         output_type=pytesseract.Output.DICT)
    except pytesseract.TesseractError as e:
        raise OcrError(f'OCR failed: {str(e)[:200]}') from e
    lines, word_list, blocks = {}, [], []
    for i, text in enumerate(data['text']):
        text = (text or '').strip()
        conf = float(data['conf'][i])
        if not text or conf < 0:
            continue
        box = [round(v * scale) for v in (data['left'][i], data['top'][i], data['width'][i], data['height'][i])]
        key = (data['block_num'][i], data['par_num'][i], data['line_num'][i])
        line = lines.setdefault(key, {'words': [], 'confs': [], 'boxes': []})
        line['words'].append(text)
        line['confs'].append(conf)
        line['boxes'].append(box)
        if words:
            word_list.append({'text': text, 'confidence': round(conf, 1), 'bbox': box})
    out_lines, paragraphs, last_par = [], [], None
    for key in sorted(lines):
        line = lines[key]
        x0 = min(b[0] for b in line['boxes'])
        y0 = min(b[1] for b in line['boxes'])
        x1 = max(b[0] + b[2] for b in line['boxes'])
        y1 = max(b[1] + b[3] for b in line['boxes'])
        text = ' '.join(line['words'])
        out_lines.append({'text': text, 'confidence': round(sum(line['confs']) / len(line['confs']), 1),
                          'bbox': [x0, y0, x1 - x0, y1 - y0]})
        if key[:2] != last_par:
            paragraphs.append([])
            last_par = key[:2]
        paragraphs[-1].append(text)
    all_confs = [c for line in lines.values() for c in line['confs']]
    result = {
        'text': '\n\n'.join('\n'.join(p) for p in paragraphs),
        'meanConfidence': round(sum(all_confs) / len(all_confs), 1) if all_confs else None,
        'lines': out_lines,
        'width': img.width,
        'height': img.height,
    }
    if words:
        result['words'] = word_list
    return result
