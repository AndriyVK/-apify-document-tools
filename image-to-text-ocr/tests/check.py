"""Checks OCR on the shared test corpus (store document-to-markdown-test-corpus).

Local mode: python -m tests.check <corpus_dir>   (runs src.ocr directly, from the Actor folder)
A rotated and a small copy of image-en.png are generated on the fly.
"""
import difflib
import re
import sys
import time
import unicodedata

from PIL import Image

from src.ocr import OcrError, detect_kind, iter_pages, ocr, rotate_upright

OCR_MIN = 0.90
PARAS = {
    'en': ['The warehouse in Lviv received 1,240 pallets of building materials during the third quarter.',
           'Delivery times improved by twelve percent after the new routing schedule was introduced.'],
    'uk': ['Склад у Львові отримав 1240 палет будівельних матеріалів протягом третього кварталу.',
           'Терміни доставки скоротилися на дванадцять відсотків після запровадження нового графіка.'],
    'ru': ['Склад во Львове получил 1240 паллет строительных материалов в течение третьего квартала.',
           'Сроки доставки сократились на двенадцать процентов после введения нового графика.'],
}
TESS = {'en': 'eng', 'uk': 'ukr', 'ru': 'rus'}


def norm(s):
    s = unicodedata.normalize('NFC', s or '').lower().replace('’', "'")
    return re.sub(r'\s+', ' ', re.sub(r'[*_`#|>\-]+', ' ', s)).strip()


def ratio(phrase, text):
    p, t = norm(phrase), norm(text)
    if p in t:
        return 1.0
    sm = difflib.SequenceMatcher(None, t, p, autojunk=False)
    best = 0.0
    for b in sm.get_matching_blocks():
        w = t[max(0, b.a - b.b):max(0, b.a - b.b) + len(p) + 10]
        best = max(best, difflib.SequenceMatcher(None, w, p, autojunk=False).ratio())
    return best


def run(path, lang, pages='', rotate=False, words=False):
    kind = detect_kind(path)
    out = []
    for page, total, img in iter_pages(path, kind, pages, None):
        angle = 0
        if rotate:
            img, angle = rotate_upright(img)
        res = ocr(img, lang, 'auto', words)
        res.update(page=page, total=total, rotated=angle)
        out.append(res)
    return out


def main():
    d = sys.argv[1]
    bad = 0

    def check(name, cond, info=''):
        nonlocal bad
        bad += not cond
        print(f"{'OK ' if cond else 'BAD'} {name} {info}")

    for lang in ('en', 'uk', 'ru'):
        t0 = time.time()
        r = run(f'{d}/image-{lang}.png', TESS[lang], words=True)[0]
        worst = min(ratio(p, r['text']) for p in PARAS[lang])
        check(f'image-{lang}.png text', worst >= OCR_MIN, f'min ratio {worst:.2f}, conf {r["meanConfidence"]}, '
              f'{time.time() - t0:.1f}s')
        check(f'image-{lang}.png lines/words', len(r['lines']) >= 3 and len(r['words']) >= 20
              and all(len(x['bbox']) == 4 for x in r['lines']))
        bx = r['lines'][0]['bbox']
        check(f'image-{lang}.png bbox inside image', bx[0] >= 0 and bx[1] >= 0 and bx[0] + bx[2] <= r['width']
              and bx[1] + bx[3] <= r['height'], str(bx))
    r = run(f'{d}/scan-noisy-uk.pdf', 'ukr+eng')
    worst = min(ratio(p, ' '.join(x['text'] for x in r)) for p in PARAS['uk'])
    check('scan-noisy-uk.pdf', worst >= OCR_MIN and r[0]['total'] >= 1, f'{len(r)} page(s), min ratio {worst:.2f}')
    r = run(f'{d}/perf-scan-20p.pdf', 'eng', pages='2-3,20')
    check('perf-scan-20p.pdf pages "2-3,20"', [x['page'] for x in r] == [2, 3, 20], str([x['page'] for x in r]))
    r = run(f'{d}/multi-frame.tiff', 'eng')
    check('multi-frame.tiff frames', [x['page'] for x in r] == [1, 2, 3])
    r = run(f'{d}/photo-sample.heic', 'eng')
    check('photo-sample.heic opens', len(r) == 1 and r[0]['width'] > 0)
    # Rotated and small copies
    im = Image.open(f'{d}/image-en.png')
    im.rotate(90, expand=True).save(f'{d}/gen-rotated.png')
    im.resize((im.width // 2, im.height // 2)).save(f'{d}/gen-small.png')
    r = run(f'{d}/gen-rotated.png', 'eng', rotate=True)[0]
    worst = min(ratio(p, r['text']) for p in PARAS['en'])
    check('rotated 90° with auto-rotate', worst >= OCR_MIN and r['rotated'] in (90, 270), f'rotated {r["rotated"]}, '
          f'min ratio {worst:.2f}')
    r = run(f'{d}/gen-small.png', 'eng')[0]
    worst = min(ratio(p, r['text']) for p in PARAS['en'])
    check('small image (upscaled)', worst >= OCR_MIN and r['width'] == im.width // 2, f'min ratio {worst:.2f}')
    for name, data in (('broken-file.pdf', None), ('random.bin', bytes(range(256)) * 40)):
        path = f'{d}/{name}'
        if data:
            open(path, 'wb').write(data)
        try:
            run(path, 'eng')
            check(f'{name} rejected', False)
        except OcrError as e:
            check(f'{name} rejected', True, str(e))
    print('FAILED' if bad else 'ALL OK', bad)
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
