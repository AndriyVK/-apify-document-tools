"""Creates or updates the Actor on Apify from this folder and builds it.

Usage: python tools/deploy.py [--no-build]
Auth: APIFY_TOKEN env var, or none when a proxy adds the Authorization header (Claude cloud network secret).
The Actor is created private; publishing in the Store is a separate, manual step.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

API = 'https://api.apify.com/v2'
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Everything the build needs: Docker files, README, Actor definition and Python sources
FILES = sorted(['Dockerfile', '.dockerignore', 'requirements.txt', 'README.md']
               + [f'.actor/{f}' for f in os.listdir(os.path.join(ROOT, '.actor')) if f.endswith('.json')]
               + [f'src/{f}' for f in os.listdir(os.path.join(ROOT, 'src')) if f.endswith('.py')])


def _headers():
    headers = {'Content-Type': 'application/json'}
    if os.environ.get('APIFY_TOKEN'):
        headers['Authorization'] = 'Bearer ' + os.environ['APIFY_TOKEN']
    return headers


def raw(path):
    with urllib.request.urlopen(urllib.request.Request(API + path, headers=_headers()), timeout=120) as r:
        return r.read().decode('utf-8', 'replace')


def call(method, path, body=None):
    req = urllib.request.Request(API + path, method=method, headers=_headers(),
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            body = json.loads(r.read() or b'{}')
            return body.get('data') if isinstance(body, dict) else body  # dataset items come as a bare list
    except urllib.error.HTTPError as e:
        sys.exit(f'{method} {path}: HTTP {e.code} {e.read().decode()[:500]}')


def main():
    meta = json.load(open(os.path.join(ROOT, '.actor/actor.json')))
    version = meta['version']
    sources = [{'name': f, 'format': 'TEXT', 'content': open(os.path.join(ROOT, f), encoding='utf-8').read()}
               for f in FILES]
    ver = {'versionNumber': version, 'sourceType': 'SOURCE_FILES', 'buildTag': 'latest', 'sourceFiles': sources}
    me = call('GET', '/users/me')
    mine = call('GET', '/acts?my=1&limit=1000')['items']
    act = next((a for a in mine if a['name'] == meta['name']), None)
    props = {'title': meta['title'], 'description': meta['description'],
             'defaultRunOptions': {'build': 'latest', 'memoryMbytes': 2048, 'timeoutSecs': 3600}}
    if act is None:
        act = call('POST', '/acts', {'name': meta['name'], 'isPublic': False, 'versions': [ver], **props})
        print(f"created {me['username']}/{meta['name']} ({act['id']})")
    else:
        call('PUT', f"/acts/{act['id']}", props)
        call('PUT', f"/acts/{act['id']}/versions/{version}", ver)
        print(f"updated {me['username']}/{meta['name']} ({act['id']}) version {version}")
    if '--no-build' in sys.argv:
        return
    build = call('POST', f"/acts/{act['id']}/builds?version={version}&tag=latest&waitForFinish=60")
    while build['status'] in ('READY', 'RUNNING'):
        time.sleep(15)
        build = call('GET', f"/actor-builds/{build['id']}?waitForFinish=60")
    print(f"build {build['buildNumber']}: {build['status']} "
          f"({build.get('stats', {}).get('computeUnits', 0):.3f} CU)")
    if build['status'] != 'SUCCEEDED':
        print(raw(f"/logs/{build['id']}")[-4000:])
        sys.exit(1)


if __name__ == '__main__':
    main()
