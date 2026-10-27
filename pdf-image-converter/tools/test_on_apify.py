"""Runs the deployed Actor on sample files from the public test corpus store and checks the produced files.

Usage: python tools/test_on_apify.py <corpus_dir>
Uploads photo-sample.heic, multi-frame.tiff and broken-file.pdf to "document-to-markdown-test-corpus" if needed.
"""
import io
import mimetypes
import os
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from deploy import API, _headers, call  # noqa: E402

ACTOR = 'pdf-image-converter'
STORE = 'document-to-markdown-test-corpus'


def put_record(store_id, key, path):
    headers = {**_headers(), 'Content-Type': mimetypes.guess_type(path)[0] or 'application/octet-stream'}
    with open(path, 'rb') as f:
        req = urllib.request.Request(f'{API}/key-value-stores/{store_id}/records/{urllib.parse.quote(key)}',
                                     data=f.read(), method='PUT', headers=headers)
    urllib.request.urlopen(req, timeout=120).read()


def run(act_id, inp):
    r = call('POST', f'/acts/{act_id}/runs?waitForFinish=60', inp)
    while r['status'] in ('READY', 'RUNNING'):
        time.sleep(5)
        r = call('GET', f"/actor-runs/{r['id']}?waitForFinish=60")
    time.sleep(30)  # charged event counters settle some seconds after the run ends
    r = call('GET', f"/actor-runs/{r['id']}")
    return r, call('GET', f"/datasets/{r['defaultDatasetId']}/items?clean=1&format=json") or []


def fetch(url):
    with urllib.request.urlopen(url, timeout=120) as resp:
        return resp.read()


def main():
    from PIL import Image
    corpus = sys.argv[1]
    act = next(a for a in call('GET', '/acts?my=1&limit=1000')['items'] if a['name'] == ACTOR)
    store = call('POST', f'/key-value-stores?name={STORE}')
    for k in ('photo-sample.heic', 'multi-frame.tiff', 'broken-file.pdf'):
        put_record(store['id'], k, f'{corpus}/{k}')
    src = lambda *keys: [{'url': f"{API}/key-value-stores/{store['id']}/records/{k}"} for k in keys]  # noqa: E731
    bad = 0

    def check(name, cond):
        nonlocal bad
        bad += not cond
        print(f"{'OK ' if cond else 'BAD'} {name}")

    r, items = run(act['id'], {'sources': src('text-3p-en.pdf', 'broken-file.pdf'), 'outputFormat': 'jpg',
                               'dpi': 100, 'pages': '2-', 'zipAll': True})
    doc = next(i for i in items if i.get('url', '') and i['url'].endswith('text-3p-en.pdf'))
    img = Image.open(io.BytesIO(fetch(doc['files'][0]['url'])))
    check('PDF pages 2- -> 2 JPG at 100 dpi', doc['count'] == 2 and img.format == 'JPEG' and abs(img.width - 827) <= 2)
    check('broken file -> error', any(i.get('error') for i in items if (i.get('url') or '').endswith('broken-file.pdf')))
    z = next((i for i in items if i.get('zip')), None)
    check('ZIP of all files', z is not None and fetch(z['files'][0]['url'])[:2] == b'PK')
    check(f"charged page=2 (got {r.get('chargedEventCounts')})", (r.get('chargedEventCounts') or {}).get('page') == 2)

    r, items = run(act['id'], {'sources': src('photo-sample.heic', 'multi-frame.tiff', 'image-en.png'),
                               'outputFormat': 'pdf', 'mergeImagesIntoOnePdf': True})
    merged = next((i for i in items if i.get('merged')), None)
    check('images -> PDF + merged.pdf with 5 pages', merged is not None and merged['count'] == 5
          and fetch(merged['files'][0]['url'])[:4] == b'%PDF')

    r, items = run(act['id'], {'sources': src('photo-sample.heic'), 'outputFormat': 'webp', 'maxWidth': 600})
    img = Image.open(io.BytesIO(fetch(items[0]['files'][0]['url'])))
    check('HEIC -> WebP 600 px', img.format == 'WEBP' and img.width == 600)

    r, items = run(act['id'], {})
    check('default input run', r['status'] == 'SUCCEEDED' and items and items[0].get('count') == 3)
    print(f"\n{'all passed' if not bad else f'{bad} failed'}")
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
