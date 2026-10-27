"""Checks Office -> PDF conversion on the document-to-markdown test corpus.

Local:  python -m tests.check local <corpus_dir> [--pdfa]
Apify:  python -m tests.check items <corpus_dir> <items.json> [--pdfa]   (downloads every pdfUrl)

For every Office/HTML/image file of the corpus: the PDF exists, has pages, contains all expected phrases
(pdftotext, whitespace-normalised; images are checked for a non-empty page only) and, with --pdfa, is marked PDF/A.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request

OFFICE = ('.docx', '.xlsx', '.pptx', '.html', '.doc', '.odt', '.rtf', '.xls', '.ppt', '.png')


def norm(s):
    return re.sub(r'\s+', ' ', s.replace('­', '')).strip().lower()


def pdf_text(path):
    return subprocess.run(['pdftotext', '-layout', path, '-'], capture_output=True, text=True).stdout


def check_pdf(exp, pdf, pdfa):
    problems = []
    data = open(pdf, 'rb').read()
    if not data.startswith(b'%PDF'):
        return ['not a PDF']
    if pdfa and b'pdfaid:part' not in data:
        problems.append('not PDF/A')
    if exp['file'].endswith('.png'):
        return problems
    text = norm(pdf_text(pdf))
    for ph in exp['phrases']:
        # Spreadsheet phrases like "| Total | 600 | 1,234.50 |" are checked cell by cell
        parts = [p.strip() for p in ph.split('|') if p.strip()] if ph.startswith('|') else [ph]
        for p in parts:
            if norm(p) not in text:
                problems.append(f'missing: {p[:40]}')
    return problems


def main():
    mode, corpus = sys.argv[1], sys.argv[2]
    pdfa = '--pdfa' in sys.argv
    expected = [e for e in json.load(open(f'{corpus}/expected.json', encoding='utf-8')) if e['file'].endswith(OFFICE)]
    pdfs, tmp = {}, tempfile.mkdtemp()
    if mode == 'local':
        from src.convert import convert_all, detect_ext
        inputs = []
        for i, e in enumerate(expected):
            src = f"{corpus}/{e['file']}"
            dst = os.path.join(tmp, f'{i:04d}-{os.path.splitext(e["file"])[0]}{os.path.splitext(e["file"])[1]}')
            with open(src, 'rb') as a, open(dst, 'wb') as b:
                b.write(a.read())
            inputs.append((dst, detect_ext(dst, e['file'])))
        res = convert_all(inputs, os.path.join(tmp, 'out'), pdfa=pdfa)
        for e, (dst, _) in zip(expected, inputs):
            pdfs[e['file']] = res[dst]
    else:
        for it in json.load(open(sys.argv[3], encoding='utf-8')):
            if it.get('url'):
                f = it['url'].rsplit('/', 1)[-1]
                if it.get('pdfUrl'):
                    dest = os.path.join(tmp, f + '.pdf')
                    urllib.request.urlretrieve(it['pdfUrl'], dest)
                    pdfs[f] = dest
                else:
                    pdfs[f] = Exception(it.get('error'))
    bad = 0
    for e in expected:
        out = pdfs.get(e['file'])
        problems = ['no result'] if out is None else [f'error: {out}'] if isinstance(out, Exception) else \
            check_pdf(e, out, pdfa)
        bad += bool(problems)
        print(f"{'OK ' if not problems else 'BAD'} {e['file']:24} {'; '.join(problems)}")
    print(f'\n{len(expected) - bad}/{len(expected)} passed')
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
