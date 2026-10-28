"""Runs the deployed Actor on real domains (TLS and WHOIS need direct connections, so they are checked here).

Usage: python tools/test_on_apify.py [--charges]
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from deploy import call  # noqa: E402

ACTOR = 'domain-whois-dns-ssl'
DOMAINS = ['google.com', 'https://www.github.com/about', 'wikipedia.org', 'bbc.co.uk', 'github.io', 'heise.de',
           'expired-rsa-dv.ssl.com', 'self-signed.badssl.com', 'this-domain-should-not-exist-829471.com', 'not a domain',
           'google.com']


def run(act_id, inp):
    r = call('POST', f'/acts/{act_id}/runs?waitForFinish=60', inp)
    while r['status'] in ('READY', 'RUNNING'):
        time.sleep(5)
        r = call('GET', f"/actor-runs/{r['id']}?waitForFinish=60")
    time.sleep(30)
    r = call('GET', f"/actor-runs/{r['id']}")
    return r, call('GET', f"/datasets/{r['defaultDatasetId']}/items?clean=1&format=json") or []


def main():
    charges = '--charges' in sys.argv
    act = next(a for a in call('GET', '/acts?my=1&limit=1000')['items'] if a['name'] == ACTOR)
    bad = 0

    def check(name, cond):
        nonlocal bad
        bad += not cond
        print(f"{'OK ' if cond else 'BAD'} {name}")

    r, items = run(act['id'], {})
    check(f"default input: {r['status']}, {len(items)} items", r['status'] == 'SUCCEEDED' and len(items) == 3)
    r, items = run(act['id'], {'domains': DOMAINS})
    print(f"  {len(items)} items, {r['stats']['runTimeSecs']:.0f}s, {r['stats']['computeUnits']:.4f} CU")
    by = {i.get('domain') or i['input']: i for i in items}
    for d, i in by.items():
        reg, ssl = i.get('registration') or {}, i.get('ssl') or {}
        print(f"    {d[:40]:40} reg={reg.get('registered')} {reg.get('source')} exp={reg.get('expiresDate')} "
              f"ssl={ssl.get('valid')} {ssl.get('daysLeft')} {ssl.get('verifyError') or ''} "
              f"mx={len((i.get('dns') or {}).get('MX', []))} {i.get('warnings') or i.get('error') or ''}")
    check('10 unique inputs -> 10 items (duplicate skipped)', len(items) == 10)
    g = by.get('google.com', {})
    check('google.com: RDAP + DNS + valid SSL', g.get('registration', {}).get('registered')
          and g.get('dns', {}).get('MX') and g.get('ssl', {}).get('valid') and g['ssl']['daysLeft'] > 0)
    check('github.com from URL', by.get('github.com', {}).get('ssl', {}).get('valid'))
    check('heise.de via WHOIS', by.get('heise.de', {}).get('registration', {}).get('source') == 'whois')
    check('github.io via WHOIS', by.get('github.io', {}).get('registration', {}).get('registered'))
    exp = by.get('expired-rsa-dv.ssl.com', {})
    check('expired certificate: valid false, daysLeft < 0, registration of ssl.com',
          exp.get('ssl', {}).get('valid') is False and exp['ssl']['daysLeft'] < 0
          and exp.get('registrableDomain') == 'ssl.com' and exp.get('registration', {}).get('registered'))
    check('self-signed: valid false', by.get('self-signed.badssl.com', {}).get('ssl', {}).get('valid') is False)
    check('unregistered domain', by.get('this-domain-should-not-exist-829471.com', {})
          .get('registration', {}).get('registered') is False)
    check('invalid input -> error', 'error' in by.get('not a domain', {}))
    if charges:
        got = (r.get('chargedEventCounts') or {}).get('domain')
        check(f'charged domain=9 (got {got})', got == 9)
    print('FAILED' if bad else 'ALL OK', bad)
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
