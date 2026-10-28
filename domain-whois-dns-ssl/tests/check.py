"""Local checks of src.domain. Usage (from the Actor folder): python -m tests.check

RDAP and DNS-over-HTTPS go over HTTPS and work behind an HTTP proxy. TLS certificates and WHOIS (port 43) need direct
connections; they are checked on Apify (tools/test_on_apify.py).
"""
import asyncio
import sys

import httpx

from src.domain import DomainError, Rdap, dns_records, normalize, parse_whois

WHOIS_SAMPLE = """Domain Name: EXAMPLE.IO
Registry Domain ID: 123
Registrar: Example Registrar, LLC
Updated Date: 2026-01-02T10:00:00Z
Creation Date: 2010-05-06T12:00:00Z
Registry Expiry Date: 2030-05-06T12:00:00Z
Domain Status: clientTransferProhibited https://icann.org/epp#clientTransferProhibited
Name Server: NS1.EXAMPLE.NET
Name Server: ns2.example.net
"""
DENIC_SAMPLE = 'Domain: nonexistent-xyz.de\nStatus: free\n'


async def main():
    bad = 0

    def check(name, cond, info=''):
        nonlocal bad
        bad += not cond
        print(f"{'OK ' if cond else 'BAD'} {name} {info}")

    for raw, exp in (('https://www.Example.com/path?q=1', 'example.com'), ('пример.укр', 'xn--e1afmkfd.xn--j1amh'),
                     ('sub.domain.co.uk.', 'sub.domain.co.uk')):
        check(f'normalize {raw}', normalize(raw) == exp, normalize(raw))
    for raw in ('not a domain', 'localhost', 'a..b.com'):
        try:
            normalize(raw)
            check(f'invalid {raw!r} rejected', False)
        except DomainError:
            check(f'invalid {raw!r} rejected', True)
    w = parse_whois(WHOIS_SAMPLE)
    check('WHOIS parse', w['registrar'] == 'Example Registrar, LLC' and w['createdDate'] == '2010-05-06'
          and w['expiresDate'] == '2030-05-06' and w['nameservers'] == ['ns1.example.net', 'ns2.example.net']
          and w['status'] == ['clientTransferProhibited'], str(w))
    check('WHOIS free domain', parse_whois(DENIC_SAMPLE) == {'registered': False})

    async with httpx.AsyncClient(timeout=20) as client:
        rdap = Rdap(client)
        r = await rdap.lookup('google.com')
        check('RDAP google.com', r['registered'] and r['source'] == 'rdap' and r['createdDate'] == '1997-09-15'
              and 'ns1.google.com' in r['nameservers'] and r['daysUntilExpiry'] > 0, str(r)[:160])
        r = await rdap.lookup('this-domain-should-not-exist-829471.com')
        check('RDAP unregistered .com', r == {'registered': False, 'source': 'rdap'}, str(r))
        r = await rdap.lookup('wikipedia.org')
        check('RDAP .org', r['registered'] and r['registrar'], str(r)[:120])
        d = await dns_records(client, 'google.com')
        check('DNS google.com', d['A'] and d['MX'] and d['NS'] and d['SPF'] and d['SPF'].startswith('v=spf1')
              and d['DMARC'] and d['DMARC'].lower().startswith('v=dmarc1'), str({k: d[k] for k in ('MX', 'SPF')}))
        d = await dns_records(client, 'this-domain-should-not-exist-829471.com')
        check('DNS of unregistered domain is empty', not d['A'] and not d['MX'] and d['SPF'] is None)
    print('FAILED' if bad else 'ALL OK', bad)
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    asyncio.run(main())
