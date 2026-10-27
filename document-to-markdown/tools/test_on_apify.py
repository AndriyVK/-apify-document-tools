"""Runs the deployed Actor on the test corpus and on two cost-measurement documents.

Usage: python tools/test_on_apify.py <corpus_dir> <work_dir>
1. Uploads the corpus to the key-value store "document-to-markdown-test-corpus" (owner's account, private).
2. Run A: the whole corpus -> <work_dir>/items.json, then `python -m tests.check items <corpus_dir> <work_dir>/items.json`.
3. Runs B and C: a 50-page text PDF and a 20-page scan -> platform cost per text page and per OCR page.
Auth as in deploy.py.
"""
import json
import mimetypes
import os
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from deploy import API, _headers, call  # noqa: E402

ACTOR = 'document-to-markdown'
STORE = 'document-to-markdown-test-corpus'


def put_record(store_id, key, path):
    ctype = mimetypes.guess_type(path)[0] or 'application/octet-stream'
    headers = {**_headers(), 'Content-Type': ctype}
    with open(path, 'rb') as f:
        req = urllib.request.Request(f'{API}/key-value-stores/{store_id}/records/{urllib.parse.quote(key)}',
                                     data=f.read(), method='PUT', headers=headers)
    urllib.request.urlopen(req, timeout=120).read()


def run(act_id, store_id, keys, extra=None):
    inp = {'sources': [{'url': f'{API}/key-value-stores/{store_id}/records/{k}'} for k in keys],
           'ocrLanguages': ['eng', 'ukr', 'rus'], 'chunkSize': 500, **(extra or {})}
    r = call('POST', f'/acts/{act_id}/runs?waitForFinish=60', inp)
    while r['status'] in ('READY', 'RUNNING'):
        time.sleep(10)
        r = call('GET', f"/actor-runs/{r['id']}?waitForFinish=60")
    items = call('GET', f"/datasets/{r['defaultDatasetId']}/items?clean=1&format=json") or []
    return r, items


def summary(name, r, items):
    text = sum(i.get('textPages') or 0 for i in items)
    ocr = sum(i.get('ocrPages') or 0 for i in items)
    usd = r.get('usageTotalUsd') or 0
    secs = (r.get('stats') or {}).get('runTimeSecs') or 0
    cu = (r.get('stats') or {}).get('computeUnits') or 0
    print(f"{name}: {r['status']}, {len(items)} items, {text} text + {ocr} OCR pages, {secs:.0f}s, {cu:.4f} CU, ${usd:.4f}")
    return text, ocr, usd


def main():
    corpus, work = sys.argv[1], sys.argv[2]
    os.makedirs(work, exist_ok=True)
    act = next(a for a in call('GET', '/acts?my=1&limit=1000')['items'] if a['name'] == ACTOR)
    store = call('POST', f'/key-value-stores?name={STORE}')
    # The Actor runs with limited permissions and cannot read other storages; synthetic test files are fine to share by ID
    call('PUT', f"/key-value-stores/{store['id']}", {'generalAccess': 'ANYONE_WITH_ID_CAN_READ'})
    expected = json.load(open(f'{corpus}/expected.json', encoding='utf-8'))
    keys = [e['file'] for e in expected]
    for k in keys + ['perf-text-50p.pdf', 'perf-scan-20p.pdf']:
        if os.path.exists(f'{corpus}/{k}'):
            put_record(store['id'], k, f'{corpus}/{k}')
    print(f"uploaded to key-value store {store['id']}")

    r, items = run(act['id'], store['id'], keys)
    summary('A corpus', r, items)
    json.dump(items, open(f'{work}/items.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

    costs = {}
    for name, key in (('B text', 'perf-text-50p.pdf'), ('C scan', 'perf-scan-20p.pdf')):
        if os.path.exists(f'{corpus}/{key}'):
            r, items = run(act['id'], store['id'], [key])
            costs[name] = summary(name, r, items)
    if 'B text' in costs and costs['B text'][0]:
        print(f"platform cost per text page ~ ${costs['B text'][2] / costs['B text'][0]:.5f} (incl. start-up)")
    if 'C scan' in costs and costs['C scan'][1]:
        print(f"platform cost per OCR page  ~ ${costs['C scan'][2] / costs['C scan'][1]:.5f} (incl. start-up)")


if __name__ == '__main__':
    main()
