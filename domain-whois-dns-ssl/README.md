# Domain WHOIS, DNS & SSL Checker: Bulk Expiry, Registrar, MX

Check hundreds of domains in one run: who registered them and when they expire, where their e-mail goes, and whether
their SSL certificate is valid — one clean JSON record per domain.

- **Registration (RDAP, WHOIS fallback):** registered or available, registrar and abuse e-mail, creation, update and
  expiry dates, **days until expiry**, status codes, nameservers, DNSSEC. RDAP covers .com, .net, .org, .ua, .uk and
  1,000+ other TLDs; WHOIS is used for the rest (.io, .de…).
- **DNS:** A, AAAA, MX, NS, TXT, CNAME, CAA, SOA, plus parsed **SPF** and **DMARC** records.
- **SSL certificate:** trusted or not (and why), issuer, subject, alternative names, valid from/to, **days left**, TLS
  version; falls back to `www.` when the bare domain has no HTTPS.
- Accepts URLs and internationalised domains; duplicates are checked once.

Use it for expiry and certificate monitoring (schedule it daily), domain portfolio audits, e-mail deliverability
checks (MX/SPF/DMARC), lead research and SEO.

## Why this Actor

| | This Actor | Typical alternatives in the Apify Store (Oct 2026) |
|---|---|---|
| **One price, three checks** | Registration + DNS + SSL for **$2 per 1,000 domains** | $2.50–3 per 1,000 for WHOIS alone, some plus start fees |
| **Coverage** | RDAP for 1,200+ TLDs with WHOIS fallback (.io, .de…) | Often WHOIS only |
| **E-mail setup** | MX, SPF and DMARC parsed | Raw TXT records |
| **Expiry monitoring** | Days until domain **and** certificate expiry in one record — schedule it daily | Two separate tools |

## Input

```json
{
  "domains": ["apify.com", "https://www.github.com/about", "wikipedia.org"],
  "whois": true,
  "dns": true,
  "ssl": true
}
```

## Output

```json
{
  "input": "apify.com",
  "domain": "apify.com",
  "registration": {
    "registered": true,
    "source": "rdap",
    "registrar": "GoDaddy.com, LLC",
    "createdDate": "2015-04-01",
    "expiresDate": "2031-04-01",
    "daysUntilExpiry": 1617,
    "status": ["client delete prohibited", "client transfer prohibited"],
    "nameservers": ["ns-1234.awsdns-26.org"],
    "dnssec": false
  },
  "dns": {
    "A": ["104.18.0.1"],
    "MX": ["1 aspmx.l.google.com"],
    "SPF": "v=spf1 include:_spf.google.com ~all",
    "DMARC": "v=DMARC1; p=reject"
  },
  "ssl": {
    "reachable": true,
    "valid": true,
    "issuer": "Google Trust Services",
    "validTo": "2027-01-10",
    "daysLeft": 75,
    "protocol": "TLSv1.3"
  }
}
```

(Values above are illustrative.) An invalid domain gets an `error` field and is **not charged**.

## Pricing

| Event | Price | What counts |
|---|---|---|
| `domain` | **$2 per 1,000** | one checked domain (registration + DNS + SSL together) |

Plus Apify's standard start fee of $0.05 per 1,000 runs. The run stops before it would exceed your maximum charge per run.

## Related Actors

- [Website Screenshot & URL/HTML to PDF](https://apify.com/ai_admin/website-screenshot) — see how the sites look
- [Document to Markdown for AI](https://apify.com/ai_admin/document-to-markdown) — PDFs and Office files → Markdown

Open source: [github.com/AndriyVK/-apify-document-tools](https://github.com/AndriyVK/-apify-document-tools)

## Use with AI agents and code

- **MCP (Claude, Cursor, VS Code, any MCP client):** add `https://mcp.apify.com?tools=ai_admin/domain-whois-dns-ssl` as an MCP server —
  the agent gets one tool with this Actor's input schema and pays per use through your Apify account.
- **One HTTP call that returns the results:**

```bash
curl -X POST "https://api.apify.com/v2/acts/ai_admin~domain-whois-dns-ssl/run-sync-get-dataset-items?token=$APIFY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"domains": ["apify.com", "github.com"], "whois": true, "dns": true, "ssl": true}'
```

## Limits

- Registries hide personal registrant data (GDPR), so owner names and e-mails are usually not available.
- Some WHOIS servers limit how often they answer; a domain may then come back with a `warnings` entry instead of
  registration data. Run large lists in a few smaller batches if that happens.
- DNS is resolved through Cloudflare's public DNS-over-HTTPS resolver.
