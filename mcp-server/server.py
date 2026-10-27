"""MCP server: document and media tools for AI agents, powered by the ai_admin Actors on Apify.

Tools: convert_document_to_markdown, convert_office_to_pdf, convert_pdf_or_images, transcribe_audio.
Each tool runs the matching Apify Actor synchronously with your own Apify API token (APIFY_TOKEN) and returns its
results. Usage is billed to your Apify account at the Actors' pay-per-event prices (see each Actor's Store page).

Run:  APIFY_TOKEN=... python server.py            (stdio transport)
"""
from __future__ import annotations

import os
from typing import Any

import httpx
from mcp.server.mcpserver import MCPServer

API = 'https://api.apify.com/v2'
SYNC_TIMEOUT = 300  # Apify keeps synchronous runs open for up to 300 s

mcp = MCPServer(
    name='apify-document-tools',
    title='Document & media tools (Apify)',
    description='Convert PDFs, scans, Office files and images to Markdown, PDF/PDF-A or images, and transcribe audio/video.',
    instructions='Give the tools public URLs of files. Results include Markdown text, JSON tables, download links '
                 'for produced files and transcripts. Requires the APIFY_TOKEN environment variable.',
    website_url='https://github.com/AndriyVK/-apify-document-tools',
    version='0.2.0',
)


async def _run_actor(actor: str, actor_input: dict[str, Any], max_charge_usd: float | None) -> list[dict]:
    token = os.environ.get('APIFY_TOKEN')
    if not token:
        raise RuntimeError('Set the APIFY_TOKEN environment variable (Apify Console → Settings → API & Integrations).')
    params = {'timeout': str(SYNC_TIMEOUT - 10), 'format': 'json', 'clean': '1'}
    if max_charge_usd:
        params['maxTotalChargeUsd'] = str(max_charge_usd)
    async with httpx.AsyncClient(timeout=SYNC_TIMEOUT + 30) as client:
        r = await client.post(f'{API}/acts/{actor.replace("/", "~")}/run-sync-get-dataset-items',
                              params=params, json=actor_input, headers={'Authorization': f'Bearer {token}'})
    if r.status_code >= 400:
        raise RuntimeError(f'Apify returned HTTP {r.status_code}: {r.text[:300]}')
    return r.json()


def _urls(urls: list[str]) -> list[dict[str, str]]:
    return [{'url': u} for u in urls if u and u.strip()]


@mcp.tool(description='Convert documents to Markdown for LLMs: PDF (text and scanned, OCR), images, DOCX/DOC, '
                      'XLSX/XLS, PPTX/PPT, ODT, RTF, HTML. Returns Markdown, tables as JSON rows and optional RAG chunks. '
                      'ocr_languages: e.g. ["eng", "ukr"]. Price: $1 per 1,000 text pages, $4 per 1,000 OCR pages.')
async def convert_document_to_markdown(urls: list[str], ocr_languages: list[str] | None = None,
                                       chunk_size: int = 0, max_charge_usd: float = 1.0) -> list[dict]:
    return await _run_actor('ai_admin/document-to-markdown',
                            {'sources': _urls(urls), 'ocrLanguages': ocr_languages or ['eng'], 'chunkSize': chunk_size},
                            max_charge_usd)


@mcp.tool(description='Convert Word, Excel, PowerPoint, OpenDocument, RTF, HTML and images to PDF, or to archival '
                      'PDF/A-2b with pdf_a=true; merge_into_one also returns a single merged PDF. Returns download links. '
                      'Price: $10 per 1,000 documents.')
async def convert_office_to_pdf(urls: list[str], pdf_a: bool = False, merge_into_one: bool = False,
                                max_charge_usd: float = 1.0) -> list[dict]:
    return await _run_actor('ai_admin/office-to-pdf',
                            {'sources': _urls(urls), 'pdfA': pdf_a, 'mergeIntoOne': merge_into_one}, max_charge_usd)


@mcp.tool(description='Render PDF pages to png/jpg/webp/tiff (dpi, pages like "1-3,5"), convert images between '
                      'formats incl. iPhone HEIC, or turn images into PDF (output_format="pdf"). Returns download links. '
                      'Price: $2 per 1,000 produced images or pages.')
async def convert_pdf_or_images(urls: list[str], output_format: str = 'png', dpi: int = 150, pages: str = '',
                                max_width: int = 0, max_charge_usd: float = 1.0) -> list[dict]:
    return await _run_actor('ai_admin/pdf-image-converter',
                            {'sources': _urls(urls), 'outputFormat': output_format, 'dpi': dpi, 'pages': pages,
                             'maxWidth': max_width}, max_charge_usd)


@mcp.tool(description='Transcribe audio or video files (MP3, WAV, M4A, MP4, MOV, WebM…) to text, timestamped '
                      'segments and SRT/VTT subtitle links with Whisper large-v3; 99 languages, language="" detects it. '
                      'Price: $5 per 1,000 audio minutes.')
async def transcribe_audio(urls: list[str], language: str = '', vocabulary: str = '',
                           max_charge_usd: float = 1.0) -> list[dict]:
    return await _run_actor('ai_admin/audio-transcriber',
                            {'sources': _urls(urls), 'language': language, 'vocabulary': vocabulary}, max_charge_usd)


@mcp.tool(description='OCR: extract text from images (PNG, JPG, WebP, TIFF, HEIC) and scanned PDF pages; returns text '
                      'per page plus lines with confidence and bounding boxes. languages: Tesseract codes, e.g. '
                      '["eng", "ukr"]; pages like "1-3". Price: $1.50 per 1,000 images or pages.')
async def ocr_images(urls: list[str], languages: list[str] | None = None, pages: str = '', auto_rotate: bool = False,
                     max_charge_usd: float = 1.0) -> list[dict]:
    return await _run_actor('ai_admin/image-to-text-ocr',
                            {'sources': _urls(urls), 'languages': languages or ['eng'], 'pages': pages,
                             'autoRotate': auto_rotate}, max_charge_usd)


if __name__ == '__main__':
    mcp.run()
