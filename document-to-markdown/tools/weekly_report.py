"""Weekly health report for the published Actors (read-only, plus one default-input run each).

Usage: python tools/weekly_report.py
For every Actor: build/notice status, users (7/30/90 days), store search positions, rating, x402 eligibility,
public run outcomes over 30 days, and a fresh run on the default input (the same check as Apify's daily auto-test).
Exit code 1 if any Actor has a notice or a failing default-input run. Auth as in deploy.py.
"""
import os
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from deploy import call  # noqa: E402

ACTORS = {
    'rjJ9rgDEj2QDspQ0M': ['document to markdown', 'pdf to markdown', 'docx to markdown', 'pdf ocr', 'ocr ukrainian',
                          'excel to markdown', 'Document to Markdown for AI'],
    'gwRuM7Y7jiidFkCRC': ['office to pdf', 'docx to pdf', 'word to pdf', 'excel to pdf', 'pdf/a',
                          'Office to PDF & PDF/A'],
    'l9zg7OIxw7cNXE8Fx': ['pdf to image', 'pdf to png', 'pdf to jpg', 'heic to jpg', 'image converter',
                          'image to pdf', 'PDF to Image & Image Converter'],
    'tTTOPBHdN4zAQBFNq': ['audio transcription', 'speech to text', 'mp3 to text', 'video to text', 'srt subtitles',
                          'ukrainian transcription', 'Audio & Video Transcriber'],
}


def report(actor_id, queries) -> bool:
    act = call('GET', f'/acts/{actor_id}')
    full = f"{act['username']}/{act['name']}"
    s = act['stats']
    print(f"\n=== {full}: public={act['isPublic']} notice={act.get('notice')} "
          f"build={act['taggedBuilds']['latest']['buildNumber']}")
    print(f"users: 7d={s.get('totalUsers7Days')} 30d={s.get('totalUsers30Days')} 90d={s.get('totalUsers90Days')} "
          f"all={s.get('totalUsers')}; runs all={s.get('totalRuns')}")

    listing = None
    print('store search positions (top 200):')
    for q in queries:
        d = call('GET', '/store?limit=200&search=' + urllib.parse.quote(q))
        pos = None
        for i, x in enumerate(d['items']):
            if f"{x['username']}/{x['name']}".lower() == full.lower():
                pos, listing = i + 1, x
        print(f"  {q!r}: {pos or '-'} of {d['total']}")
    if listing:
        r = listing['stats'].get('publicActorRunStats30Days') or {}
        print(f"store listing: rating={listing.get('actorReviewRating')} ({listing.get('actorReviewCount')} reviews), "
              f"bookmarks={listing.get('bookmarkCount')}, x402={listing.get('isWhiteListedForAgenticPayments')}; "
              f"public runs 30d: {r}")

    run = call('POST', f'/acts/{actor_id}/runs?waitForFinish=120')
    while run['status'] in ('READY', 'RUNNING'):
        time.sleep(5)
        run = call('GET', f"/actor-runs/{run['id']}?waitForFinish=60")
    items = call('GET', f"/datasets/{run['defaultDatasetId']}/items?clean=1") or []
    ok = run['status'] == 'SUCCEEDED' and bool(items) and not items[0].get('error')
    print(f"default-input run: {run['status']}, {(run.get('stats') or {}).get('runTimeSecs', 0):.0f}s, "
          f"items={len(items)} -> {'OK' if ok else 'PROBLEM'} (run {run['id']})")
    return ok and act.get('notice') in (None, 'NONE')


def main():
    results = [report(a, q) for a, q in ACTORS.items()]
    if not all(results):
        sys.exit(1)


if __name__ == '__main__':
    main()
