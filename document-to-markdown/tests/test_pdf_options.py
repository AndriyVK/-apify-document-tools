"""PDF password, page range and header/footer removal: PYTHONPATH=. python3 tests/test_pdf_options.py
Needs reportlab and pypdf locally (test only, not in the Actor image)."""
import os
import sys
import tempfile

from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas

from src.convert import ConversionError, convert, parse_page_range

bad = 0


def check(name, cond):
    global bad
    bad += not cond
    print(f"{'OK ' if cond else 'BAD'} {name}")


with tempfile.TemporaryDirectory() as d:
    plain, locked = os.path.join(d, 'plain.pdf'), os.path.join(d, 'locked.pdf')
    c = canvas.Canvas(plain)
    for i in range(1, 6):
        c.setFont('Helvetica', 9)
        c.drawString(72, 800, 'ACME Corp - Annual Report 2026')
        c.setFont('Helvetica', 12)
        c.drawString(72, 700, f'Section {i} body text about results number {i * 7}.')
        c.setFont('Helvetica', 9)
        c.drawString(280, 40, f'Page {i} of 5')
        c.showPage()
    c.save()
    w = PdfWriter()
    for p in PdfReader(plain).pages:
        w.add_page(p)
    w.encrypt('s3cret')
    w.write(locked)

    r = convert(plain, '.pdf', page_range='2-3, 5', remove_headers_footers=True)
    check('page range 2-3,5 -> 3 pages charged', r.page_count == 3)
    check('headers/footers removed, body kept', 'ACME' not in r.markdown and 'Page 2' not in r.markdown
          and all(f'Section {i} body' in r.markdown for i in (2, 3, 5)) and 'Section 1 ' not in r.markdown)
    r = convert(plain, '.pdf')
    check('without the option everything stays', 'ACME' in r.markdown and 'Page 5 of 5' in r.markdown)
    for pw, expect in ((None, 'password-protected'), ('bad', 'wrong PDF password')):
        try:
            convert(locked, '.pdf', password=pw)
            check(f'locked PDF, password={pw}: error', False)
        except ConversionError as e:
            check(f'locked PDF, password={pw}: "{e}"', expect in str(e))
    r = convert(locked, '.pdf', password='s3cret')
    check('locked PDF opens with the password', r.page_count == 5 and 'Section 4 body' in r.markdown)
    check('range parser', parse_page_range('1-3, 5, 10-', 12) == [0, 1, 2, 4, 9, 10, 11]
          and parse_page_range('-2', 5) == [0, 1])
    try:
        convert(plain, '.pdf', page_range='7-9')
        check('range outside -> error', False)
    except ConversionError:
        check('range outside -> error', True)
print('FAILED' if bad else 'ALL OK', bad)
sys.exit(1 if bad else 0)
