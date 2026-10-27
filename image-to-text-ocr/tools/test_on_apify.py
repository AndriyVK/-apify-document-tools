"""Runs the deployed Actor on the public test corpus store and checks the results.

Usage: python tools/test_on_apify.py [--charges]   (--charges: also check charged events, once PPE pricing is set)
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from deploy import API, call  # noqa: E402

ACTOR = 'image-to-text-ocr'
STORE = 'FloomuI2DrQCJazY8'  # document-to-markdown-test-corpus, readable by anyone with the ID
EN = 'The warehouse in Lviv received 1,240 pallets'
UK = 'Склад у Львові отримав 1240 палет'


def run(act_id, inp):
    r = call('POST', f'/acts/{act_id}/runs?waitForFinish=60', inp)
    while r['status'] in ('READY', 'RUNNING'):
        time.sleep(5)
        r = call('GET', f"/actor-runs/{r['id']}?waitForFinish=60")
    time.sleep(30)  # charged event counters settle some seconds after the run ends
    r = call('GET', f"/actor-runs/{r['id']}")
    return r, call('GET', f"/datasets/{r['defaultDatasetId']}/items?clean=1&format=json") or []


def main():
    charges = '--charges' in sys.argv
    act = next(a for a in call('GET', '/acts?my=1&limit=1000')['items'] if a['name'] == ACTOR)
    src = lambda *keys: [{'url': f'{API}/key-value-stores/{STORE}/records/{k}'} for k in keys]  # noqa: E731
    bad = 0

    def check(name, cond):
        nonlocal bad
        bad += not cond
        print(f"{'OK ' if cond else 'BAD'} {name}")

    r, items = run(act['id'], {})
    check(f"default input: {r['status']}, {len(items)} item(s)", r['status'] == 'SUCCEEDED' and len(items) == 1
          and EN in items[0].get('text', ''))
    r, items = run(act['id'], {'sources': src('image-uk.png', 'scan-noisy-uk.pdf', 'perf-scan-20p.pdf',
                                              'multi-frame.tiff', 'broken-file.pdf'),
                               'languages': ['ukr', 'eng'], 'pages': '1-2', 'includeWords': True})
    by = {}
    for it in items:
        by.setdefault(it['url'].rsplit('/', 1)[-1], []).append(it)
    print(f"  {r['status']}, {len(items)} items, {r['stats'].get('runTimeSecs', 0):.0f}s, "
          f"usage ${r.get('usageTotalUsd', 0):.4f}")
    check('image-uk.png text', UK in by['image-uk.png'][0].get('text', '') and by['image-uk.png'][0].get('words'))
    check('scan-noisy-uk.pdf text', UK in by['scan-noisy-uk.pdf'][0].get('text', ''))
    check('perf-scan-20p.pdf pages 1-2', [x['page'] for x in by['perf-scan-20p.pdf']] == [1, 2])
    check('multi-frame.tiff frames 1-2', [x['page'] for x in by['multi-frame.tiff']] == [1, 2])
    check('broken-file.pdf error', 'error' in by['broken-file.pdf'][0])
    if charges:
        got = (r.get('chargedEventCounts') or {}).get('image')
        check(f'charged image=6 (got {got})', got == 6)  # 1 + 1 + 2 + 2 pages; the broken file is free
    print('FAILED' if bad else 'ALL OK', bad)
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
