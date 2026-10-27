"""Runs the deployed Actor on the Office part of the test corpus (already uploaded by document-to-markdown's
test_on_apify.py to the key-value store "document-to-markdown-test-corpus") and saves dataset items.

Usage: python tools/test_on_apify.py <corpus_dir> <work_dir>
Then:  python -m tests.check items <corpus_dir> <work_dir>/items.json
       python -m tests.check items <corpus_dir> <work_dir>/items-pdfa.json --pdfa
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from deploy import API, call  # noqa: E402

OFFICE = ('.docx', '.xlsx', '.pptx', '.html', '.doc', '.odt', '.rtf', '.xls', '.ppt', '.png')


def run(act_id, inp):
    r = call('POST', f'/acts/{act_id}/runs?waitForFinish=60', inp)
    while r['status'] in ('READY', 'RUNNING'):
        time.sleep(10)
        r = call('GET', f"/actor-runs/{r['id']}?waitForFinish=60")
    time.sleep(30)  # charged event counters settle some seconds after the run ends
    r = call('GET', f"/actor-runs/{r['id']}")
    return r, call('GET', f"/datasets/{r['defaultDatasetId']}/items?clean=1&format=json") or []


def main():
    corpus, work = sys.argv[1], sys.argv[2]
    os.makedirs(work, exist_ok=True)
    act = next(a for a in call('GET', '/acts?my=1&limit=1000')['items'] if a['name'] == 'office-to-pdf')
    store = call('POST', '/key-value-stores?name=document-to-markdown-test-corpus')
    keys = [e['file'] for e in json.load(open(f'{corpus}/expected.json')) if e['file'].endswith(OFFICE)]
    urls = [{'url': f"{API}/key-value-stores/{store['id']}/records/{k}"} for k in keys]
    for name, extra in (('items.json', {}), ('items-pdfa.json', {'pdfA': True, 'mergeIntoOne': True})):
        r, items = run(act['id'], {'sources': urls, **extra})
        st = r.get('stats') or {}
        print(f"{name}: {r['status']}, {len(items)} items, {st.get('runTimeSecs', 0):.0f}s, "
              f"{st.get('computeUnits', 0):.4f} CU, ${r.get('usageTotalUsd') or 0:.4f}, charged {r.get('chargedEventCounts')}")
        merged = [i for i in items if i.get('merged')]
        if merged:
            print(f"  merged.pdf: {merged[0]['pages']} pages from {merged[0]['documents']} documents")
        json.dump(items, open(f'{work}/{name}', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
