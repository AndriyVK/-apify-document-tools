"""Builds the test corpus: documents with known content plus expected.json.

Usage: python tests/make_corpus.py <out_dir>
Needs: reportlab, python-docx, python-pptx, openpyxl, pypdfium2, Pillow, LibreOffice (soffice) for legacy formats.
"""
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile

import pypdfium2 as pdfium
from docx import Document
from openpyxl import Workbook
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from pptx import Presentation
from pptx.util import Inches
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
FONT_BOLD = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
pdfmetrics.registerFont(TTFont('DejaVu', FONT))
pdfmetrics.registerFont(TTFont('DejaVu-Bold', FONT_BOLD))

TEXTS = {
    'en': {
        'title': 'Quarterly Supply Report',
        'paras': ['The warehouse in Lviv received 1,240 pallets of building materials during the third quarter.',
                  'Delivery times improved by twelve percent after the new routing schedule was introduced.'],
        'table': [['Item', 'Quantity', 'Price'], ['Cement', '420', '96.50'], ['Steel rods', '180', '412.00']],
    },
    'uk': {
        'title': 'Звіт про постачання',
        'paras': ['Склад у Львові отримав 1240 палет будівельних матеріалів протягом третього кварталу.',
                  'Терміни доставки скоротилися на дванадцять відсотків після запровадження нового графіка.'],
        'table': [['Товар', 'Кількість', 'Ціна'], ['Цемент', '420', '96,50'], ['Арматура', '180', '412,00']],
    },
    'ru': {
        'title': 'Отчёт о поставках',
        'paras': ['Склад во Львове получил 1240 паллет строительных материалов в течение третьего квартала.',
                  'Сроки доставки сократились на двенадцать процентов после введения нового графика.'],
        'table': [['Товар', 'Количество', 'Цена'], ['Цемент', '420', '96,50'], ['Арматура', '180', '412,00']],
    },
}


def expect(name, lang, *, ocr=False, table=True, heading=True, pages=None, extra=None):
    t = TEXTS[lang]
    e = {'file': name, 'lang': lang, 'ocr': ocr, 'phrases': t['paras'] + (extra or []),
         'heading': t['title'] if heading else None, 'table_cells': [c for r in t['table'] for c in r] if table else []}
    if pages:
        e['pages'] = pages
    return e


def pdf_text(path, lang, pages=1):
    t = TEXTS[lang]
    h = ParagraphStyle('h', fontName='DejaVu-Bold', fontSize=20, leading=24)
    p = ParagraphStyle('p', fontName='DejaVu', fontSize=10.5, leading=14)
    story = []
    for n in range(pages):
        story += [Paragraph(t['title'] if n == 0 else f"{t['title']} {n + 1}", h), Spacer(1, 10)]
        story += [Paragraph(x, p) for x in t['paras']]
        story += [Spacer(1, 10)]
        tbl = Table(t['table'])
        tbl.setStyle(TableStyle([('FONTNAME', (0, 0), (-1, -1), 'DejaVu'), ('GRID', (0, 0), (-1, -1), 0.5, colors.black)]))
        story += [tbl]
        if n < pages - 1:
            story.append(PageBreak())
    SimpleDocTemplate(path, pagesize=A4).build(story)


def pdf_scan(src_pdf, path, dpi=200, noise=True, angle=0.0):
    doc = pdfium.PdfDocument(src_pdf)
    imgs = []
    for page in doc:
        img = page.render(scale=dpi / 72).to_pil().convert('L')
        if angle:
            img = img.rotate(angle, expand=True, fillcolor=255)
        if noise:
            rnd = random.Random(7)
            px = img.load()
            for _ in range(img.width * img.height // 400):
                x, y = rnd.randrange(img.width), rnd.randrange(img.height)
                px[x, y] = rnd.choice((0, 255))
            img = img.filter(ImageFilter.GaussianBlur(0.4))
        imgs.append(img.convert('RGB'))
    imgs[0].save(path, save_all=True, append_images=imgs[1:], resolution=dpi)


def image_text(path, lang):
    t = TEXTS[lang]
    img = Image.new('RGB', (1800, 700), 'white')
    d = ImageDraw.Draw(img)
    d.text((60, 50), t['title'], font=ImageFont.truetype(FONT_BOLD, 56), fill='black')
    f = ImageFont.truetype(FONT, 30)
    y = 170
    for para in t['paras']:
        words, line = para.split(), ''
        for w in words:
            if d.textlength(line + ' ' + w, font=f) > 1650:
                d.text((60, y), line.strip(), font=f, fill='black')
                y, line = y + 44, ''
            line += ' ' + w
        d.text((60, y), line.strip(), font=f, fill='black')
        y += 80
    img.save(path)


def docx(path, lang, bullets=True):
    t = TEXTS[lang]
    d = Document()
    d.add_heading(t['title'], level=1)
    for x in t['paras']:
        d.add_paragraph(x)
    if bullets:
        d.add_paragraph(t['table'][1][0], style='List Bullet')
        d.add_paragraph(t['table'][2][0], style='List Bullet')
    tbl = d.add_table(rows=0, cols=3)
    for row in t['table']:
        cells = tbl.add_row().cells
        for c, v in zip(cells, row):
            c.text = v
    d.save(path)


def xlsx(path, lang):
    t = TEXTS[lang]
    wb = Workbook()
    ws = wb.active
    ws.title = 'Data'
    for row in t['table']:
        ws.append(row)
    ws.append(['Total', 600, 1234.5])  # numeric cells: shown by their number format
    ws.cell(row=ws.max_row, column=3).number_format = '#,##0.00'
    ws2 = wb.create_sheet('Notes')
    for x in t['paras']:
        ws2.append([x])
    wb.save(path)


def pptx(path, lang):
    t = TEXTS[lang]
    prs = Presentation()
    s = prs.slides.add_slide(prs.slide_layouts[1])
    s.shapes.title.text = t['title']
    s.placeholders[1].text = t['paras'][0]
    s2 = prs.slides.add_slide(prs.slide_layouts[5])
    s2.shapes.title.text = t['paras'][1]
    rows = t['table']
    shape = s2.shapes.add_table(len(rows), 3, Inches(1), Inches(2), Inches(6), Inches(1.5))
    for i, r in enumerate(rows):
        for j, v in enumerate(r):
            shape.table.cell(i, j).text = v
    prs.save(path)


def html(path, lang):
    t = TEXTS[lang]
    rows = ''.join('<tr>' + ''.join(f'<td>{c}</td>' for c in r) + '</tr>' for r in t['table'])
    body = ''.join(f'<p>{p}</p>' for p in t['paras'])
    with open(path, 'w', encoding='utf-8') as f:
        f.write(f'<!doctype html><html><head><meta charset="utf-8"><title>{t["title"]}</title></head>'
                f'<body><nav>menu</nav><h1>{t["title"]}</h1>{body}<table>{rows}</table></body></html>')


def soffice(src, target, outdir):
    profile = tempfile.mkdtemp()
    subprocess.run(['soffice', f'-env:UserInstallation=file://{profile}', '--headless', '--convert-to', target,
                    '--outdir', outdir, src], check=True, capture_output=True, timeout=180)
    shutil.rmtree(profile, ignore_errors=True)


def main(out):
    os.makedirs(out, exist_ok=True)
    tmp = tempfile.mkdtemp()
    exp = []
    for lang in ('en', 'uk', 'ru'):
        # text PDFs: single page and multi-page
        pdf_text(f'{out}/text-{lang}.pdf', lang)
        exp.append(expect(f'text-{lang}.pdf', lang, pages=1))
        pdf_text(f'{out}/text-3p-{lang}.pdf', lang, pages=3)
        exp.append(expect(f'text-3p-{lang}.pdf', lang, pages=3))
        # scans: clean 300 dpi, noisy 200 dpi, slightly rotated
        pdf_scan(f'{out}/text-{lang}.pdf', f'{out}/scan-{lang}.pdf', dpi=300, noise=False)
        exp.append(expect(f'scan-{lang}.pdf', lang, ocr=True, table=False, heading=False, pages=1))
        pdf_scan(f'{out}/text-{lang}.pdf', f'{out}/scan-noisy-{lang}.pdf', dpi=200, noise=True, angle=0.8)
        exp.append(expect(f'scan-noisy-{lang}.pdf', lang, ocr=True, table=False, heading=False, pages=1))
        image_text(f'{out}/image-{lang}.png', lang)
        exp.append(expect(f'image-{lang}.png', lang, ocr=True, table=False, heading=False))
        docx(f'{out}/doc-{lang}.docx', lang)
        exp.append(expect(f'doc-{lang}.docx', lang))
        xlsx(f'{out}/sheet-{lang}.xlsx', lang)
        exp.append(expect(f'sheet-{lang}.xlsx', lang, heading=False, extra=['| Total | 600 | 1,234.50 |']))
        pptx(f'{out}/slides-{lang}.pptx', lang)
        exp.append(expect(f'slides-{lang}.pptx', lang, heading=True))
        html(f'{out}/page-{lang}.html', lang)
        exp.append(expect(f'page-{lang}.html', lang))
    # legacy formats from the Ukrainian sources
    # .doc from .odt: LibreOffice drops python-docx tables (no column widths) when writing .doc directly
    soffice(f'{out}/doc-uk.docx', 'odt', tmp)
    soffice(f'{tmp}/doc-uk.odt', 'doc', tmp)
    soffice(f'{out}/doc-en.docx', 'rtf', tmp)
    soffice(f'{out}/sheet-uk.xlsx', 'xls', tmp)
    soffice(f'{out}/slides-uk.pptx', 'ppt', tmp)
    # RTF written by LibreOffice keeps no heading style, so the title arrives as plain text
    for src, lang, heading in (('doc-uk.doc', 'uk', True), ('doc-uk.odt', 'uk', True), ('doc-en.rtf', 'en', False),
                               ('sheet-uk.xls', 'uk', False), ('slides-uk.ppt', 'uk', True)):
        shutil.move(f'{tmp}/{src}', f'{out}/legacy-{src}')
        extra = ['| Total | 600 | 1,234.50 |'] if src.endswith('.xls') else None
        exp.append(expect(f'legacy-{src}', lang, heading=heading, extra=extra))
    with open(f'{out}/expected.json', 'w', encoding='utf-8') as f:
        json.dump(exp, f, ensure_ascii=False, indent=1)
    print(f'{len(exp)} documents in {out}')


if __name__ == '__main__':
    main(sys.argv[1])
