"""Apify Actor: bulk domain WHOIS/RDAP, DNS records and SSL certificate check."""
from __future__ import annotations

import asyncio

import httpx
from apify import Actor

from .domain import DomainError, Rdap, dns_records, normalize, registrable, tls_certificate

EVENT_DOMAIN = 'domain'
CONCURRENCY = 8


async def inspect(client: httpx.AsyncClient, rdap: Rdap, domain: str, do_whois: bool, do_dns: bool,
                  do_ssl: bool) -> dict:
    item: dict = {'domain': domain}
    warnings = []
    if do_whois:
        reg_name = registrable(domain)
        if reg_name != domain:
            item['registrableDomain'] = reg_name
        try:
            item['registration'] = await rdap.lookup(reg_name)
        except (DomainError, httpx.HTTPError) as e:
            warnings.append(f'registration: {e}')
    if do_dns:
        try:
            item['dns'] = await dns_records(client, domain)
        except httpx.HTTPError as e:
            warnings.append(f'dns: {e}')
    if do_ssl and (item.get('registration') or {}).get('registered', True):
        item['ssl'] = await asyncio.to_thread(tls_certificate, domain)
        if not item['ssl'].get('reachable'):  # many sites answer only on www
            www = await asyncio.to_thread(tls_certificate, 'www.' + domain)
            if www.get('reachable'):
                item['ssl'] = {**www, 'host': 'www.' + domain}
    if warnings:
        item['warnings'] = warnings
    return item


async def main() -> None:
    async with Actor:
        inp = await Actor.get_input() or {}
        raw = [str(d) for d in (inp.get('domains') or []) if str(d).strip()]
        if not raw:
            await Actor.fail(status_message='Input "domains" is empty: add at least one domain.')
            return
        do_whois, do_dns, do_ssl = (bool(inp.get(k, True)) for k in ('whois', 'dns', 'ssl'))
        charging = Actor.get_charging_manager()
        sem = asyncio.Semaphore(CONCURRENCY)
        lock = asyncio.Lock()
        counts = {'ok': 0, 'failed': 0, 'skipped': 0, 'in_flight': 0}
        seen = set()

        async with httpx.AsyncClient(timeout=httpx.Timeout(20, connect=10),
                                     headers={'User-Agent': 'domain-whois-dns-ssl (Apify Actor)'}) as client:
            rdap = Rdap(client)

            async def check(raw_domain: str) -> None:
                try:
                    domain = normalize(raw_domain)
                except DomainError as e:
                    counts['failed'] += 1
                    await Actor.push_data({'input': raw_domain, 'error': str(e)})
                    return
                if domain in seen:
                    return
                seen.add(domain)
                async with sem:
                    async with lock:  # reserve a charge before the work, so the user's limit is never exceeded
                        left = charging.calculate_max_event_charge_count_within_limit(EVENT_DOMAIN)
                        if left is not None and left <= counts['in_flight']:
                            counts['skipped'] += 1
                            return
                        counts['in_flight'] += 1
                    try:
                        item = await inspect(client, rdap, domain, do_whois, do_dns, do_ssl)
                        await Actor.push_data({'input': raw_domain, **item})
                        # One event per checked domain, after the result is saved
                        await Actor.charge(EVENT_DOMAIN)
                        counts['ok'] += 1
                    finally:
                        counts['in_flight'] -= 1

            await asyncio.gather(*(check(d) for d in raw))
        if counts['skipped']:
            Actor.log.warning(f"Maximum charge per run reached, {counts['skipped']} domain(s) skipped.")
        await Actor.set_status_message(f"Checked {counts['ok']} domain(s), invalid {counts['failed']}, "
                                       f"skipped {counts['skipped']}.")
