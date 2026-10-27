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

import pdfplumber
import pypdfium2 as pdfium
import pytesseract
from PIL import Image, ImageOps

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
    try:
        text = pytesseract.image_to_string(img, lang=langs, config='--psm 3')
    except pytesseract.TesseractError as e:
        raise ConversionError(f'OCR failed: {e}') from e
    # Tesseract keeps line breaks inside paragraphs; join them, keep blank-line paragraph breaks
    paras = [re.sub(r'\s*\n\s*', ' ', p).strip() for p in re.split(r'\n\s*\n', text)]
    return '\n\n'.join(p for p in paras if p)


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
