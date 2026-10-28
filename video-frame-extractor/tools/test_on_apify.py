"""Runs the deployed Actor on the public test corpus store and checks the results.

Usage: python tools/test_on_apify.py [--charges]   (--charges: also check charged events, once PPE pricing is set)
"""
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from deploy import API, call  # noqa: E402

ACTOR = 'video-frame-extractor'
STORE = 'FloomuI2DrQCJazY8'  # document-to-markdown-test-corpus, readable by anyone with the ID


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
    it = items[0] if items else {}
    print(f"  {r['status']}, {r['stats'].get('runTimeSecs', 0):.0f}s, usage ${r.get('usageTotalUsd', 0):.4f}")
    check(f"default input: 6 frames ({it.get('frameCount')})", r['status'] == 'SUCCEEDED' and it.get('frameCount') == 6)
    with urllib.request.urlopen(it['frames'][0]['url'], timeout=60) as resp:
        check('frame link downloads a JPEG', resp.read(3) == b'\xff\xd8\xff')
    with urllib.request.urlopen(it['contactSheetUrl'], timeout=60) as resp:
        check('contact sheet downloads', resp.read(3) == b'\xff\xd8\xff')
    r, items = run(act['id'], {'sources': src('video-en.mp4', 'speech-en.mp3'), 'mode': 'timestamps',
                               'timestamps': ['5', '0:20', '999'], 'format': 'webp', 'maxWidth': 160,
                               'contactSheet': False})
    by = {i['url'].rsplit('/', 1)[-1]: i for i in items}
    v = by.get('video-en.mp4', {})
    check('timestamps 5 and 20 (999 skipped)', [f['time'] for f in v.get('frames', [])] == [5, 20])
    check('webp keys', all(f['key'].endswith('.webp') for f in v.get('frames', [])))
    check('mp3 without video -> error', 'error' in by.get('speech-en.mp3', {}))
    if charges:
        got = (r.get('chargedEventCounts') or {}).get('frame')
        check(f'charged frame=2 (got {got})', got == 2)
    print('FAILED' if bad else 'ALL OK', bad)
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
