"""Runs the deployed Actor on public pages and checks the results; prints the platform cost per page.

Usage: python tools/test_on_apify.py [--charges]   (--charges: also check charged events, once PPE pricing is set)
"""
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from deploy import call  # noqa: E402

ACTOR = 'website-screenshot'
PAGES = ['https://apify.com', 'https://en.wikipedia.org/wiki/Ukraine', 'https://www.bbc.com/news',
         'https://github.com/AndriyVK/-apify-document-tools', 'https://docs.python.org/3/']


def run(act_id, inp):
    r = call('POST', f'/acts/{act_id}/runs?waitForFinish=60', inp)
    while r['status'] in ('READY', 'RUNNING'):
        time.sleep(5)
        r = call('GET', f"/actor-runs/{r['id']}?waitForFinish=60")
    time.sleep(30)  # charged event counters settle some seconds after the run ends
    r = call('GET', f"/actor-runs/{r['id']}")
    return r, call('GET', f"/datasets/{r['defaultDatasetId']}/items?clean=1&format=json") or []


def head(url, n=4):
    with urllib.request.urlopen(url, timeout=60) as resp:
        return resp.read(n)


def main():
    charges = '--charges' in sys.argv
    act = next(a for a in call('GET', '/acts?my=1&limit=1000')['items'] if a['name'] == ACTOR)
    bad = 0

    def check(name, cond):
        nonlocal bad
        bad += not cond
        print(f"{'OK ' if cond else 'BAD'} {name}")

    r, items = run(act['id'], {})
    it = items[0] if items else {}
    check(f"default input: {r['status']}, status {it.get('status')}, {it.get('width')}x{it.get('height')}",
          r['status'] == 'SUCCEEDED' and it.get('status') == 200 and head(it['fileUrl']) == b'\x89PNG')
    r, items = run(act['id'], {'urls': [{'url': u} for u in PAGES] + [{'url': 'http://169.254.169.254/'}],
                               'device': 'mobile', 'format': 'jpeg'})
    secs = r['stats'].get('runTimeSecs', 0)
    print(f"  {len(items)} items, {secs:.0f}s, usage ${r.get('usageTotalUsd', 0):.4f} "
          f"(${r.get('usageTotalUsd', 0) / len(PAGES):.5f} per page)")
    for i in items:
        print(f"    {i.get('status')} {i.get('width')}x{i.get('height')} banners={i.get('bannersHidden')} "
              f"{i['url'][:50]} {i.get('error', '')[:80]}")
    good = [i for i in items if i.get('fileUrl')]
    check(f'{len(good)}/{len(PAGES)} public pages captured', len(good) >= len(PAGES) - 1)
    check('metadata address blocked', any('private' in i.get('error', '') for i in items))
    check('jpeg files', all(head(i['fileUrl'], 3) == b'\xff\xd8\xff' for i in good))
    r, items = run(act['id'], {'urls': [], 'html': '<h1>Invoice #42</h1><p>Total: €120</p>', 'format': 'pdf'})
    check('raw HTML to PDF', items and head(items[0]['fileUrl']) == b'%PDF')
    if charges:
        got = (r.get('chargedEventCounts') or {}).get('screenshot')
        check(f'charged screenshot=1 (got {got})', got == 1)
    print('FAILED' if bad else 'ALL OK', bad)
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
