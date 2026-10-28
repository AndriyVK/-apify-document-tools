# MCP server: document & media tools for AI agents

Tools for Claude, Cursor, ChatGPT and any other MCP client, backed by open-source Actors on Apify:

| Tool | What it does | Price (billed by Apify) |
|---|---|---|
| `convert_document_to_markdown` | PDF (text and scanned, OCR in 11 languages), images, DOCX/DOC, XLSX/XLS, PPTX/PPT, ODT, RTF, HTML → Markdown, JSON tables, RAG chunks | $1 / 1,000 text pages, $4 / 1,000 OCR pages |
| `convert_office_to_pdf` | Word, Excel, PowerPoint, OpenDocument, RTF, HTML, images → PDF or PDF/A-2b, optional merge | $10 / 1,000 documents |
| `convert_pdf_or_images` | PDF pages → PNG/JPG/WebP/TIFF, images ↔ PDF, iPhone HEIC → JPG, resize | $2 / 1,000 images |
| `transcribe_audio` | Audio and video → text, timestamped segments, SRT/VTT (Whisper large-v3, 99 languages) | $5 / 1,000 minutes |
| `ocr_images` | Images and scanned PDFs → text, lines with confidence and boxes (38 languages incl. Ukrainian) | $1.50 / 1,000 images |
| `text_to_speech` | Text or PDF/DOCX/HTML → natural speech MP3/WAV/OGG + SRT subtitles (37 voices, 23 languages incl. Ukrainian) | $10 / 1,000 audio minutes ($40 high quality) |
| `screenshot_website` | Web pages or your HTML → full-page PNG/JPEG/WebP screenshots or PDF; desktop, tablet, mobile; one element by CSS selector | $4 / 1,000 pages |
| `check_domains` | Bulk WHOIS/RDAP (registrar, expiry, days left), DNS records (A, MX, NS, TXT…), SSL certificate expiry | $2 / 1,000 domains |
| `extract_video_frames` | Video → frames with timecodes: evenly spaced, every N seconds, exact times, scene changes or keyframes; contact sheet | $1 / 1,000 frames |

Every tool takes public file URLs and a `max_charge_usd` safety limit per call (default $1).

## Option 1 — hosted (no install)

Use Apify's hosted MCP server with exactly these tools:

```json
{
  "mcpServers": {
    "document-tools": {
      "url": "https://mcp.apify.com?tools=ai_admin/document-to-markdown,ai_admin/office-to-pdf,ai_admin/pdf-image-converter,ai_admin/audio-transcriber,ai_admin/image-to-text-ocr,ai_admin/text-to-speech,ai_admin/website-screenshot,ai_admin/domain-whois-dns-ssl,ai_admin/video-frame-extractor"
    }
  }
}
```

On first connection your browser opens to sign in to Apify (or pass `Authorization: Bearer <APIFY_TOKEN>`).

## Option 2 — local (stdio)

```bash
git clone https://github.com/AndriyVK/-apify-document-tools
cd -- -apify-document-tools/mcp-server
pip install -r requirements.txt
```

```json
{
  "mcpServers": {
    "document-tools": {
      "command": "python",
      "args": ["/path/to/-apify-document-tools/mcp-server/server.py"],
      "env": { "APIFY_TOKEN": "your Apify API token" }
    }
  }
}
```

Get the token in Apify Console → Settings → API & Integrations. New Apify accounts include free monthly usage credit.

## Source

The Actors behind the tools live in the parent folders of this repository (MIT licence).
