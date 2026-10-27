"""Local checks for pdf-image-converter.

Usage: python -m tests.check <corpus_dir>   (corpus from document-to-markdown/tests/make_corpus.py)
Builds extra samples (JPEG, 3-frame TIFF, HEIC, broken file) in a temp dir and checks every conversion path.
"""
import os
import sys
import tempfile

from PIL import Image

from src.convert import ConversionError, convert_image, detect_kind, images_to_one_pdf, parse_pages, pdf_to_images


def expect(cond, msg, results):
    results.append((bool(cond), msg))


def main():
    corpus = sys.argv[1]
    tmp = tempfile.mkdtemp()
    out = os.path.join(tmp, 'out')
    os.makedirs(out)
    r = []
    pdf3 = f'{corpus}/text-3p-en.pdf'
    png = f'{corpus}/image-en.png'

    expect(parse_pages('', 5) == [0, 1, 2, 3, 4] and parse_pages('1-2,4-', 5) == [0, 1, 3, 4]
           and parse_pages('3', 2) == [], 'page ranges', r)
    expect(detect_kind(pdf3) == 'pdf' and detect_kind(png) == 'image', 'detect pdf/image by content', r)

    for fmt, ext in (('PNG', 'png'), ('JPEG', 'jpg'), ('WEBP', 'webp')):
        files, total, _ = pdf_to_images(pdf3, out, f'p-{ext}', fmt=fmt, dpi=100, pages='', quality=80,
                                        max_width=0, limit=None)
        ok = total == 3 and len(files) == 3 and all(f.endswith('.' + ext) for f in files)
        with Image.open(files[0]) as im:
            ok = ok and im.format == fmt and abs(im.width - round(595 * 100 / 72)) <= 2
        expect(ok, f'PDF 3 pages -> {ext} at 100 dpi', r)

    files, _, warn = pdf_to_images(pdf3, out, 'range', fmt='PNG', dpi=72, pages='2-', quality=80, max_width=0,
                                   limit=1)
    expect(len(files) == 1 and files[0].endswith('p0002.png') and warn, 'page range 2- with charge limit 1', r)

    files = convert_image(png, out, 'img-pdf', fmt='PDF', quality=85, max_width=0)
    with open(files[0], 'rb') as f:
        expect(f.read(4) == b'%PDF', 'PNG -> PDF', r)
    files = convert_image(png, out, 'img-jpg', fmt='JPEG', quality=85, max_width=800)
    with Image.open(files[0]) as im:
        expect(im.format == 'JPEG' and im.width == 800, 'PNG -> JPG resized to 800 px', r)

    tiff = os.path.join(tmp, 'multi.tiff')
    frames = [Image.new('RGB', (200, 100), c) for c in ('red', 'green', 'blue')]
    frames[0].save(tiff, save_all=True, append_images=frames[1:])
    files = convert_image(tiff, out, 'tiff', fmt='PNG', quality=85, max_width=0)
    expect(len(files) == 3, '3-frame TIFF -> 3 PNG', r)
    files = convert_image(tiff, out, 'tiff-pdf', fmt='PDF', quality=85, max_width=0)
    expect(len(files) == 1, '3-frame TIFF -> one PDF', r)

    try:
        from pillow_heif import register_heif_opener  # noqa: F401
        heic = os.path.join(tmp, 'photo.heic')
        Image.new('RGB', (300, 200), 'orange').save(heic, 'HEIF')
        files = convert_image(heic, out, 'heic', fmt='JPEG', quality=85, max_width=0)
        with Image.open(files[0]) as im:
            expect(detect_kind(heic) == 'image' and im.format == 'JPEG' and im.size == (300, 200), 'HEIC -> JPG', r)
    except ImportError:
        expect(False, 'HEIC -> JPG (pillow-heif not installed)', r)

    merged = os.path.join(out, 'merged.pdf')
    expect(images_to_one_pdf([png, tiff], merged, 0) == 4, 'merge PNG + 3-frame TIFF -> 4-page PDF', r)

    broken = os.path.join(tmp, 'broken.pdf')
    with open(broken, 'wb') as f:
        f.write(os.urandom(4000))
    try:
        detect_kind(broken, 'broken.pdf')
        expect(False, 'broken file rejected', r)
    except ConversionError:
        expect(True, 'broken file rejected', r)

    for ok, msg in r:
        print(f"{'OK ' if ok else 'BAD'} {msg}")
    bad = sum(not ok for ok, _ in r)
    print(f'\n{len(r) - bad}/{len(r)} passed')
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
