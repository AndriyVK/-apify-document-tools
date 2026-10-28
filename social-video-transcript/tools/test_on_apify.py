"""Runs the Actor on Apify with one input and prints each item, the run's cost and charged events.

Usage: python tools/test_on_apify.py '<input JSON>' [label]"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from deploy import call  # noqa: E402

inp = json.loads(sys.argv[1])
label = sys.argv[2] if len(sys.argv) > 2 else ''
act = next(a for a in call('GET', '/acts?my=1&limit=1000')['items'] if a['name'] == 'social-video-transcript')
r = call('POST', f"/acts/{act['id']}/runs?waitForFinish=60", inp)
while r['status'] in ('READY', 'RUNNING'):
    time.sleep(10)
    r = call('GET', f"/actor-runs/{r['id']}?waitForFinish=60")
time.sleep(5)
r = call('GET', f"/actor-runs/{r['id']}")
items = call('GET', f"/datasets/{r['defaultDatasetId']}/items")
print(f"== {label} status={r['status']} {r.get('statusMessage')} items={len(items)} usd={r.get('usageTotalUsd') or 0:.4f} "
      f"proxyGB={(r.get('usage') or {}).get('PROXY_RESIDENTIAL_TRANSFER_GBYTES', 0):.5f} "
      f"charged={r.get('chargedEventCounts')}")
for i in items:
    tr = i.get('translation') or {}
    print(f"  {i.get('platform', ''):9} {i.get('transcriptSource') or 'ERR':19} {i.get('language')} "
          f"{i.get('durationSeconds')}s {len(i.get('segments') or [])}seg {i['url'][:60]}")
    print(f"      {(i.get('error') or i.get('text') or '')[:160]}")
    if tr:
        print(f"      [{tr.get('language')}] {tr.get('text', '')[:160]}")
    if i.get('warnings'):
        print(f"      warnings: {i['warnings']}")
