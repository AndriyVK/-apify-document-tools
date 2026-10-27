"""PDF pages -> images, images -> PDF, image format conversion (pypdfium2 + Pillow, HEIC via pillow-heif)."""
from __future__ import annotations

import os
import re

import pypdfium2 as pdfium
from PIL import Image, ImageOps

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:  # HEIC support is optional for local runs
    pass

IMAGE_EXT = {'.png', '.jpg', '.jpeg', '.webp', '.tif', '.tiff', '.bmp', '.gif', '.heic', '.heif', '.avif'}
OUTPUT_FORMATS = {'png': 'PNG', 'jpg': 'JPEG', 'webp': 'WEBP', 'tiff': 'TIFF', 'pdf': 'PDF'}


class ConversionError(Exception):
    pass


def detect_kind(path: str, name_hint: str = '', content_type: str = '') -> str:
    """'pdf' or 'image' (by magic bytes first, so wrong extensions don't matter)."""
    with open(path, 'rb') as f:
        head = f.read(1024)
    if b'%PDF' in head:
        return 'pdf'
    if (head.startswith((b'\x89PNG', b'\xff\xd8', b'GIF8', b'BM', b'II*\x00', b'MM\x00*'))
            or head[8:12] == b'WEBP' or head[4:12] in (b'ftypheic', b'ftypheix', b'ftypmif1', b'ftypavif', b'ftyphevc')):
        return 'image'
    ext = os.path.splitext((name_hint or path).split('?')[0])[1].lower()
    if ext == '.pdf' or content_type.startswith('application/pdf'):
        raise ConversionError('not a valid PDF file (damaged or wrong extension)')
    raise ConversionError(f'unsupported file type (name {name_hint!r}, content type {content_type!r})')


def parse_pages(spec: str, count: int) -> list[int]:
    """'1-3,5,8-' -> zero-based page indexes within range; empty spec = all pages."""
    if not spec or not spec.strip():
        return list(range(count))
    pages = []
    for part in spec.replace(' ', '').split(','):
        m = re.fullmatch(r'(\d*)-(\d*)|(\d+)', part)
        if not m:
            raise ConversionError(f'invalid page range {part!r} (use e.g. "1-3,5,8-")')
        if m.group(3):
            a = b = int(m.group(3))
        else:
            a, b = int(m.group(1) or 1), int(m.group(2) or count)
        pages.extend(i - 1 for i in range(max(a, 1), min(b, count) + 1))
    return sorted(set(pages))


def _prepare(img: Image.Image, fmt: str, max_width: int) -> Image.Image:
    img = ImageOps.exif_transpose(img)
    if max_width and img.width > max_width:
        img = img.resize((max_width, round(img.height * max_width / img.width)), Image.LANCZOS)
    if fmt in ('JPEG', 'PDF') and img.mode not in ('RGB', 'L'):
        bg = Image.new('RGB', img.size, 'white')
        bg.paste(img.convert('RGBA'), mask=img.convert('RGBA').split()[-1])
        img = bg
    return img


def save_image(img: Image.Image, dest: str, fmt: str, quality: int) -> None:
    kwargs = {'quality': quality} if fmt in ('JPEG', 'WEBP') else {}
    if fmt == 'PNG':
        kwargs['optimize'] = True
    img.save(dest, fmt, **kwargs)


def pdf_to_images(path: str, outdir: str, stem: str, *, fmt: str, dpi: int, pages: str, quality: int,
                  max_width: int, limit: int | None) -> tuple[list[str], int, list[str]]:
    """Returns (output paths, total pages in the PDF, warnings)."""
    try:
        doc = pdfium.PdfDocument(path)
    except pdfium.PdfiumError as e:
        raise ConversionError(f'cannot open PDF (damaged or password-protected): {e}') from e
    warnings = []
    try:
        total = len(doc)
        idx = parse_pages(pages, total)
        if limit is not None and len(idx) > limit:
            warnings.append(f'only {limit} of {len(idx)} pages converted: maximum charge per run reached')
            idx = idx[:limit]
        out = []
        for i in idx:
            img = _prepare(doc[i].render(scale=dpi / 72).to_pil(), fmt, max_width)
            dest = os.path.join(outdir, f'{stem}-p{i + 1:04d}.{fmt.lower().replace("jpeg", "jpg")}')
            save_image(img, dest, fmt, quality)
            out.append(dest)
        return out, total, warnings
    finally:
        doc.close()


def convert_image(path: str, outdir: str, stem: str, *, fmt: str, quality: int, max_width: int) -> list[str]:
    """One output per frame (multi-page TIFF/GIF); for PDF output all frames go into one PDF."""
    try:
        img = Image.open(path)
        frames = [_prepare(f.copy(), fmt, max_width) for f in _frames(img)]
    except Exception as e:  # noqa: BLE001 - Pillow raises many types for broken files
        raise ConversionError(f'cannot open image (damaged or unsupported): {e}') from e
    ext = fmt.lower().replace('jpeg', 'jpg')
    if fmt == 'PDF':
        dest = os.path.join(outdir, f'{stem}.pdf')
        frames[0].save(dest, 'PDF', save_all=True, append_images=frames[1:], resolution=150)
        return [dest]
    out = []
    for n, frame in enumerate(frames):
        dest = os.path.join(outdir, f'{stem}{"" if len(frames) == 1 else f"-f{n + 1:03d}"}.{ext}')
        save_image(frame, dest, fmt, quality)
        out.append(dest)
    return out


def _frames(img: Image.Image):
    for i in range(getattr(img, 'n_frames', 1)):
        img.seek(i)
        yield img


def images_to_one_pdf(paths: list[str], dest: str, max_width: int) -> int:
    frames = []
    for p in paths:
        with Image.open(p) as img:
            frames.extend(_prepare(f.copy(), 'PDF', max_width) for f in _frames(img))
    frames[0].save(dest, 'PDF', save_all=True, append_images=frames[1:], resolution=150)
    return len(frames)
