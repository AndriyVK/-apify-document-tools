"""Domain registration (RDAP, WHOIS fallback), DNS records (DNS over HTTPS) and TLS certificate checks."""
from __future__ import annotations

import asyncio
import datetime as dt
import re
import socket
import ssl

import httpx
import tldextract
from cryptography import x509
from cryptography.x509.oid import ExtensionOID, NameOID

RDAP_BOOTSTRAP = 'https://data.iana.org/rdap/dns.json'
DOH = 'https://cloudflare-dns.com/dns-query'
DNS_TYPES = ('A', 'AAAA', 'MX', 'NS', 'TXT', 'CNAME', 'CAA', 'SOA')
WHOIS_FIELDS = {
    'registrar': r'(?:Registrar|registrar|Sponsoring Registrar|registrar name)\s*:\s*(.+)',
    'createdDate': r'(?:Creation Date|created|Registered on|Registration Time|Created On|domain_dateregistered)\s*:\s*(.+)',
    'updatedDate': r'(?:Updated Date|changed|Last updated|modified|Last Modified)\s*:\s*(.+)',
    'expiresDate': r'(?:Registry Expiry Date|Expiration Date|Expiry date|expires|paid-till|Expiration Time|Expiry Date)\s*:\s*(.+)',
}
NOT_FOUND = re.compile(r'no match|not found|no data found|no entries found|status:\s*free|is available|'
                       r'domain not found|object does not exist|no object found', re.I)


_PSL = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)  # bundled Public Suffix List snapshot, no network


class DomainError(Exception):
    pass


def registrable(domain: str) -> str:
    """expired.badssl.com -> badssl.com, www.bbc.co.uk -> bbc.co.uk: registries know only the registered name."""
    return _PSL(domain).top_domain_under_public_suffix or domain


def normalize(raw: str) -> str:
    d = raw.strip().lower()
    d = re.sub(r'^[a-z][a-z0-9+.-]*://', '', d).split('/')[0].split('?')[0].split(':')[0].strip('.')
    if d.startswith('www.'):
        d = d[4:]
    try:
        d = d.encode('idna').decode('ascii')
    except UnicodeError as e:
        raise DomainError(f'"{raw}" is not a valid domain') from e
    if not re.fullmatch(r'(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9-]{2,63}', d):
        raise DomainError(f'"{raw}" is not a valid domain')
    return d


class Rdap:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client
        self.servers: dict[str, str] | None = None
        self.whois_servers: dict[str, str | None] = {}

    async def _bootstrap(self) -> dict[str, str]:
        if self.servers is None:
            r = await self.client.get(RDAP_BOOTSTRAP)
            r.raise_for_status()
            self.servers = {tld: urls[0] for tlds, urls in r.json()['services'] for tld in tlds}
        return self.servers

    async def lookup(self, domain: str) -> dict:
        """Registration data; falls back to WHOIS for TLDs without RDAP (e.g. .io, .de)."""
        tld = domain.rsplit('.', 1)[-1]
        server = (await self._bootstrap()).get(tld)
        if server:
            try:
                r = await self.client.get(server.rstrip('/') + '/domain/' + domain,
                                          headers={'Accept': 'application/rdap+json'}, follow_redirects=True)
                if r.status_code == 404:
                    return {'registered': False, 'source': 'rdap'}
                if r.status_code < 400:
                    return {'registered': True, 'source': 'rdap', **parse_rdap(r.json())}
            except (httpx.HTTPError, ValueError):
                pass
        return await self.whois(domain)

    async def whois(self, domain: str) -> dict:
        tld = domain.rsplit('.', 1)[-1]
        if tld not in self.whois_servers:
            text = await asyncio.to_thread(whois_query, 'whois.iana.org', tld)
            m = re.search(r'^(?:refer|whois):\s*(\S+)', text, re.M)
            self.whois_servers[tld] = m.group(1) if m else None
        server = self.whois_servers[tld]
        if not server:
            raise DomainError(f'no RDAP or WHOIS service is known for .{tld}')
        text = await asyncio.to_thread(whois_query, server, domain)
        return {'source': 'whois', **parse_whois(text)}


def _connect(host: str, port: int, timeout: float) -> socket.socket:
    """IPv4 addresses first: Apify has no IPv6 route, and some servers list IPv6 first."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise OSError(f'cannot resolve {host}') from e
    infos.sort(key=lambda i: i[0] != socket.AF_INET)
    last = None
    for family, stype, proto, _, addr in infos:
        sock = socket.socket(family, stype, proto)
        sock.settimeout(timeout)
        try:
            sock.connect(addr)
            return sock
        except OSError as e:
            sock.close()
            last = e
    raise last or OSError(f'no address for {host}')


def whois_query(server: str, query: str, timeout: float = 15) -> str:
    for attempt in range(2):
        try:
            with _connect(server, 43, timeout) as s:
                s.sendall(query.encode() + b'\r\n')
                chunks = []
                while chunk := s.recv(65536):
                    chunks.append(chunk)
                    if sum(map(len, chunks)) > 1 << 20:
                        break
            return b''.join(chunks).decode('utf-8', 'replace')
        except OSError as e:
            if attempt:
                raise DomainError(f'WHOIS server {server} did not answer: {e}') from e
    return ''



def _date(s: str | None) -> str | None:
    if not s:
        return None
    s = s.strip()
    for fmt in ('%Y-%m-%dT%H:%M:%SZ', '%Y-%m-%dT%H:%M:%S.%fZ', '%Y-%m-%dT%H:%M:%S%z', '%Y-%m-%d %H:%M:%S',
                '%Y-%m-%d', '%d-%b-%Y', '%Y.%m.%d', '%d.%m.%Y', '%Y/%m/%d', '%Y-%m-%dT%H:%M:%S'):
        try:
            d = dt.datetime.strptime(s.split(' (')[0][:32], fmt)
            return d.date().isoformat()
        except ValueError:
            continue
    m = re.search(r'\d{4}-\d{2}-\d{2}', s)
    return m.group(0) if m else s[:40]


def _days_left(date: str | None) -> int | None:
    try:
        return (dt.date.fromisoformat(date) - dt.date.today()).days if date else None
    except ValueError:
        return None


def parse_rdap(d: dict) -> dict:
    events = {e.get('eventAction'): e.get('eventDate') for e in d.get('events', [])}
    registrar, abuse = None, None
    org = country = None
    for ent in d.get('entities', []):
        roles = ent.get('roles', [])
        vcard = {f[0]: f[3] for f in (ent.get('vcardArray') or [None, []])[1] if len(f) > 3}
        if 'registrar' in roles:
            registrar = vcard.get('fn') or ent.get('handle')
            for sub in ent.get('entities', []):
                if 'abuse' in sub.get('roles', []):
                    sv = {f[0]: f[3] for f in (sub.get('vcardArray') or [None, []])[1] if len(f) > 3}
                    abuse = sv.get('email')
        if 'registrant' in roles:
            org = vcard.get('org') or vcard.get('fn')
            adr = vcard.get('adr')
            if isinstance(adr, list) and adr:
                country = adr[-1] or None
    expires = _date(events.get('expiration'))
    return {
        'registrar': registrar, 'registrarAbuseEmail': abuse,
        'createdDate': _date(events.get('registration')), 'updatedDate': _date(events.get('last changed')),
        'expiresDate': expires, 'daysUntilExpiry': _days_left(expires),
        'status': d.get('status', []),
        'nameservers': sorted(n.get('ldhName', '').lower() for n in d.get('nameservers', []) if n.get('ldhName')),
        'dnssec': (d.get('secureDNS') or {}).get('delegationSigned'),
        'registrantOrganization': org if org and 'redacted' not in str(org).lower() else None,
        'registrantCountry': country if isinstance(country, str) and len(country) <= 40 else None,
    }


def parse_whois(text: str) -> dict:
    if NOT_FOUND.search(text[:2000]) and not re.search(r'Creation Date|created:', text, re.I):
        return {'registered': False}
    out = {'registered': True}
    for key, pattern in WHOIS_FIELDS.items():
        m = re.search(pattern, text, re.I)
        out[key] = (_date(m.group(1)) if key.endswith('Date') else m.group(1).strip()[:200]) if m else None
    out['daysUntilExpiry'] = _days_left(out.get('expiresDate'))
    ns = re.findall(r'(?:Name Server|nserver|Nameservers?)\s*:\s*([a-z0-9.-]+)', text, re.I)
    out['nameservers'] = sorted({n.lower().rstrip('.') for n in ns})
    out['status'] = sorted(set(re.findall(r'(?:Domain Status|status)\s*:\s*([A-Za-z]+)', text)))[:10]
    return out


async def dns_records(client: httpx.AsyncClient, domain: str, types=DNS_TYPES) -> dict:
    async def one(name, rtype):
        r = await client.get(DOH, params={'name': name, 'type': rtype}, headers={'Accept': 'application/dns-json'})
        r.raise_for_status()
        data = r.json()
        code = {'A': 1, 'NS': 2, 'CNAME': 5, 'SOA': 6, 'MX': 15, 'TXT': 16, 'AAAA': 28, 'CAA': 257}[rtype]
        out = []
        for a in data.get('Answer', []):
            if a.get('type') != code:
                continue
            v = re.sub(r'"\s*"', '', a['data']).strip('"') if rtype == 'TXT' else a['data']
            out.append(v.rstrip('.') if rtype in ('MX', 'NS', 'CNAME') else v)
        return out
    results = await asyncio.gather(*(one(domain, t) for t in types), one('_dmarc.' + domain, 'TXT'),
                                   return_exceptions=True)
    out = {}
    for t, res in zip((*types, 'DMARC'), results):
        out[t] = [] if isinstance(res, Exception) else res
    out['SPF'] = next((t for t in out.get('TXT', []) if t.lower().startswith('v=spf1')), None)
    out['DMARC'] = next((t for t in out.pop('DMARC') if t.lower().startswith('v=dmarc1')), None)
    out['MX'] = sorted(out.get('MX', []), key=lambda m: int(m.split()[0]) if m.split()[0].isdigit() else 99)
    return out


def tls_certificate(host: str, port: int = 443, timeout: float = 10) -> dict:
    """Certificate of host:443, checked against the system trust store; details are read even when invalid.
    A connection reset is retried once (some servers drop the first handshake)."""
    res = _tls_certificate(host, port, timeout)
    if not res.get('reachable') and 'reset' in res.get('error', '').lower():
        res = _tls_certificate(host, port, timeout)
    return res


def _tls_certificate(host: str, port: int, timeout: float) -> dict:
    verify_error = None
    der = None
    ctx = ssl.create_default_context()
    try:
        with _connect(host, port, timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as tls:
                der, proto = tls.getpeercert(binary_form=True), tls.version()
    except ssl.SSLCertVerificationError as e:
        verify_error = e.verify_message or str(e)
    except (OSError, ssl.SSLError) as e:
        return {'reachable': False, 'error': str(e)[:200]}
    if der is None:
        insecure = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        insecure.check_hostname = False
        insecure.verify_mode = ssl.CERT_NONE
        try:
            with _connect(host, port, timeout) as sock:
                with insecure.wrap_socket(sock, server_hostname=host) as tls:
                    der, proto = tls.getpeercert(binary_form=True), tls.version()
        except (OSError, ssl.SSLError) as e:
            return {'reachable': False, 'error': str(e)[:200]}
    cert = x509.load_der_x509_certificate(der)

    def name(n, oid):
        v = n.get_attributes_for_oid(oid)
        return v[0].value if v else None
    try:
        sans = cert.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME).value.get_values_for_type(
            x509.DNSName)
    except x509.ExtensionNotFound:
        sans = []
    not_after = cert.not_valid_after_utc
    return {
        'reachable': True, 'valid': verify_error is None, 'verifyError': verify_error, 'protocol': proto,
        'subject': name(cert.subject, NameOID.COMMON_NAME),
        'issuer': name(cert.issuer, NameOID.ORGANIZATION_NAME) or name(cert.issuer, NameOID.COMMON_NAME),
        'validFrom': cert.not_valid_before_utc.date().isoformat(), 'validTo': not_after.date().isoformat(),
        'daysLeft': (not_after - dt.datetime.now(dt.timezone.utc)).days,
        'san': sans[:100],
    }
