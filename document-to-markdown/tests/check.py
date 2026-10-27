"""Checks conversion results against expected.json.

Local mode:  python -m tests.check local <corpus_dir>          (runs src.convert directly)
Apify mode:  python -m tests.check items <corpus_dir> <items.json>  (dataset items from a run; item url ends with file name)

Text sources: every phrase, the heading and all table cells must be present exactly (whitespace-normalised).
OCR sources: every phrase must match with similarity >= OCR_MIN (difflib on normalised text).
"""
import difflib
import json
import re
import sys
import time
import unicodedata

OCR_MIN = 0.90


def norm(s):
    s = unicodedata.normalize('NFC', s or '').lower().replace('’', "'")
    s = re.sub(r'[*_`#|>\-]+', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


def best_ratio(phrase, text):
    p, t = norm(phrase), norm(text)
    if p in t:
        return 1.0
    sm = difflib.SequenceMatcher(None, t, p, autojunk=False)
    best = 0.0
    for block in sm.get_matching_blocks():
        start = max(0, block.a - block.b)
        window = t[start:start + len(p) + 10]
        best = max(best, difflib.SequenceMatcher(None, window, p, autojunk=False).ratio())
    return best


def check_one(exp, item):
    problems = []
    if item.get('error'):
        return [f"error: {item['error']}"]
    md = item.get('markdown', '')
    for ph in exp['phrases']:
        r = best_ratio(ph, md)
        if (exp['ocr'] and r < OCR_MIN) or (not exp['ocr'] and r < 1.0):
            problems.append(f'phrase {r:.2f}: {ph[:50]}')
    if exp.get('heading') and not re.search(r'^#+\s*' + re.escape(exp['heading']), md, re.M):
        problems.append(f"no heading: {exp['heading']}")
    if exp['table_cells']:
        cells = {norm(c) for t in item.get('tables', []) for r in t for c in r}
        missing = [c for c in exp['table_cells'] if norm(c) not in cells]
        if missing:
            problems.append(f'table cells missing: {missing}')
    if exp.get('pages'):
        got = (item.get('textPages') or 0) + (item.get('ocrPages') or 0)
        if got != exp['pages']:
            problems.append(f"pages {got} != {exp['pages']}")
    if exp['ocr'] and not item.get('ocrPages'):
        problems.append('OCR was not used')
    return problems


def report(expected, items_by_file):
    bad = 0
    for exp in expected:
        item = items_by_file.get(exp['file'])
        problems = ['no result'] if item is None else check_one(exp, item)
        mark = 'OK ' if not problems else 'BAD'
        bad += bool(problems)
        extra = f" {item.get('textPages')}+{item.get('ocrPages')}p {item.get('seconds', '')}s" if item else ''
        print(f"{mark} {exp['file']:28}{extra}  {'; '.join(problems)}")
    print(f'\n{len(expected) - bad}/{len(expected)} passed')
    return bad


def main():
    mode, corpus = sys.argv[1], sys.argv[2]
    expected = json.load(open(f'{corpus}/expected.json', encoding='utf-8'))
    items = {}
    if mode == 'local':
        from src.convert import chunk_markdown, convert, detect_ext, extract_tables
        for exp in expected:
            path = f"{corpus}/{exp['file']}"
            t = time.monotonic()
            try:
                res = convert(path, detect_ext(path, exp['file']), ocr_languages='eng+ukr+rus')
                items[exp['file']] = {'markdown': res.markdown, 'tables': extract_tables(res.markdown),
                                      'textPages': res.page_count, 'ocrPages': res.ocr_pages,
                                      'chunks': chunk_markdown(res.markdown, 500),
                                      'seconds': round(time.monotonic() - t, 2)}
            except Exception as e:  # noqa: BLE001
                items[exp['file']] = {'error': repr(e)}
    else:
        for it in json.load(open(sys.argv[3], encoding='utf-8')):
            items[it['url'].rsplit('/', 1)[-1].split('?')[0]] = it
    sys.exit(1 if report(expected, items) else 0)


if __name__ == '__main__':
    main()
