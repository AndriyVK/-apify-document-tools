# Apify document tools

Open-source [Apify](https://apify.com) Actors for working with business documents. Run them in the cloud with no setup
from Apify Store, call them from your code, or plug them into AI agents through the Apify MCP server.

| Actor | What it does | Run it |
|---|---|---|
| [Document to Markdown for AI](document-to-markdown/) | PDF, scanned PDF and images (OCR in 11 languages incl. Ukrainian and Russian), DOCX, XLSX, PPTX, legacy Office and HTML → Markdown, JSON tables and RAG chunks | [apify.com/ai_admin/document-to-markdown](https://apify.com/ai_admin/document-to-markdown) |
| [Office to PDF & PDF/A](office-to-pdf/) | Word, Excel, PowerPoint, OpenDocument, RTF, HTML and images → PDF or archival PDF/A-2b, optional merge into one PDF | [apify.com/ai_admin/office-to-pdf](https://apify.com/ai_admin/office-to-pdf) |
| [Audio & Video Transcriber](audio-transcriber/) | Audio and video → text, timestamped segments and SRT/VTT subtitles with Whisper large-v3 (via Groq), 99 languages | [apify.com/ai_admin/audio-transcriber](https://apify.com/ai_admin/audio-transcriber) |
| [PDF to Image & Image Converter](pdf-image-converter/) | PDF pages → PNG/JPG/WebP/TIFF, images → PDF, image formats incl. iPhone HEIC, resize, ZIP | [apify.com/ai_admin/pdf-image-converter](https://apify.com/ai_admin/pdf-image-converter) |
| [Image to Text OCR](image-to-text-ocr/) | Images and scanned PDFs → text, lines and words with confidence and boxes, 38 languages incl. Ukrainian, auto-rotate | [apify.com/ai_admin/image-to-text-ocr](https://apify.com/ai_admin/image-to-text-ocr) |

Ready-made examples (Apify tasks): [document-to-markdown examples](https://apify.com/ai_admin/document-to-markdown/examples),
[office-to-pdf examples](https://apify.com/ai_admin/office-to-pdf/examples),
[OCR examples](https://apify.com/ai_admin/image-to-text-ocr/examples).

## Use from AI agents (MCP)

All Actors are available as MCP tools — hosted (no install):
`https://mcp.apify.com?tools=ai_admin/document-to-markdown,ai_admin/office-to-pdf,ai_admin/pdf-image-converter,ai_admin/audio-transcriber,ai_admin/image-to-text-ocr`
— or as a local stdio server in [mcp-server/](mcp-server/).

## Built with

LibreOffice, Tesseract OCR, [pdfplumber](https://github.com/jsvine/pdfplumber), [pypdfium2](https://github.com/pypdfium2-team/pypdfium2),
[markitdown](https://github.com/microsoft/markitdown), [openpyxl](https://openpyxl.readthedocs.io), [pypdf](https://github.com/py-pdf/pypdf)
and the [Apify Python SDK](https://docs.apify.com/sdk/python).

## Development

Each Actor folder is self-contained (`Dockerfile`, `.actor/`, `src/`, `tests/`):

```bash
cd document-to-markdown
python tests/make_corpus.py /tmp/corpus          # 32 sample documents with known content (needs LibreOffice)
python -m tests.check local /tmp/corpus          # convert locally and compare with the expected content
python tools/deploy.py                           # create/update the Actor on Apify (APIFY_TOKEN) and build it

cd ../office-to-pdf
python -m tests.check local /tmp/corpus --pdfa   # Office -> PDF/A on the same corpus

cd ../audio-transcriber
GROQ_API_KEY=... python -m tests.check /path/to/media   # real Groq calls; see tests/check.py for the sample files

cd ../pdf-image-converter
python -m tests.check /tmp/corpus                # PDF <-> image conversions

cd ../image-to-text-ocr
python -m tests.check /tmp/corpus                # OCR of images, scans, TIFF, HEIC, rotated pages
```

Local runs need Tesseract (`eng`, `ukr`, `rus`), LibreOffice and the packages from `requirements.txt`.

Bug reports with a sample document (or a similar public file) are welcome as GitHub issues.

## License

MIT
