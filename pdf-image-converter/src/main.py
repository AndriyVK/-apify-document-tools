"""Apify Actor: PDF pages to PNG/JPG/WebP, images to PDF, image format conversion (incl. iPhone HEIC)."""
from __future__ import annotations

import asyncio
import mimetypes
import os
import re
import tempfile
import zipfile

import httpx
from apify import Actor

from .convert import OUTPUT_FORMATS, ConversionError, convert_image, detect_kind, images_to_one_pdf, pdf_to_images
from .download import DownloadError, download

EVENT_PAGE = 'page'


def _sources(inp: dict) -> list[str]:
    urls = []
    for item in inp.get('sources') or []:
        url = item.get('url') if isinstance(item, dict) else item
        if isinstance(url, str) and url.strip():
            urls.append(url.strip())
    return urls


def _stem(name: str, idx: int) -> str:
    stem = re.sub(r'[^A-Za-z0-9._-]+', '-', os.path.splitext(name or '')[0]).strip('-.')[:60]
    return f'{idx:04d}-{stem or "file"}'


async def main() -> None:
    async with Actor:
        inp = await Actor.get_input() or {}
        urls = _sources(inp)
        if not urls:
            await Actor.fail(status_message='Input "sources" is empty: add at least one file URL.')
            return
        fmt = OUTPUT_FORMATS.get(str(inp.get('outputFormat', 'png')).lower())
        if not fmt:
            await Actor.fail(status_message=f'outputFormat must be one of {", ".join(OUTPUT_FORMATS)}.')
            return
        dpi = min(max(int(inp.get('dpi') or 150), 36), 600)
        quality = min(max(int(inp.get('quality') or 85), 10), 100)
        max_width = int(inp.get('maxWidth') or 0)
        pages_spec = inp.get('pages') or ''
        merge_images = bool(inp.get('mergeImagesIntoOnePdf', False))
        make_zip = bool(inp.get('zipAll', False))

        charging = Actor.get_charging_manager()
        store = await Actor.open_key_value_store()
        all_outputs, image_inputs = [], []
        ok = failed = 0
        with tempfile.TemporaryDirectory() as tmp:
            async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=20),
                                         headers={'User-Agent': 'pdf-image-converter (Apify Actor)'}) as client:
                for idx, url in enumerate(urls, 1):
                    item = {'url': url}
                    left = charging.calculate_max_event_charge_count_within_limit(EVENT_PAGE)
                    if left == 0:
                        Actor.log.warning('Maximum charge per run reached, remaining files were skipped.')
                        break
                    src = os.path.join(tmp, f'in-{idx:04d}')
                    outdir = os.path.join(tmp, f'out-{idx:04d}')
                    os.makedirs(outdir)
                    try:
                        name, ctype = await download(client, url, src)
                        kind = detect_kind(src, name, ctype)
                        stem = _stem(name, idx)
                        warnings = []
                        if kind == 'pdf':
                            if fmt == 'PDF':
                                raise ConversionError('the file is already a PDF; choose png, jpg, webp or tiff')
                            outs, total, warnings = await asyncio.to_thread(
                                pdf_to_images, src, outdir, stem, fmt=fmt, dpi=dpi, pages=pages_spec,
                                quality=quality, max_width=max_width, limit=left)
                            item['sourcePages'] = total
                        else:
                            outs = await asyncio.to_thread(convert_image, src, outdir, stem, fmt=fmt,
                                                           quality=quality, max_width=max_width)
                            if left is not None and len(outs) > left:
                                warnings.append(f'only {left} of {len(outs)} frames kept: maximum charge per run reached')
                                outs = outs[:left]
                            image_inputs.append(src)
                    except (DownloadError, ConversionError, httpx.HTTPError) as e:
                        failed += 1
                        item['error'] = str(e) or type(e).__name__
                        await Actor.push_data(item)
                        continue
                    files = []
                    for p in outs:
                        key = os.path.basename(p)
                        with open(p, 'rb') as f:
                            await store.set_value(key, f.read(), content_type=mimetypes.guess_type(p)[0])
                        files.append({'key': key, 'url': await store.get_public_url(key), 'bytes': os.path.getsize(p)})
                        all_outputs.append(p)
                    item.update(fileName=name or None, kind=kind, outputFormat=fmt.lower(), count=len(files),
                                files=files, warnings=warnings)
                    await Actor.push_data(item)
                    # One event per produced page or image, after the files are saved
                    if files:
                        await Actor.charge(EVENT_PAGE, count=len(files))
                    ok += 1

            if merge_images and len(image_inputs) > 0 and fmt != 'PDF':
                Actor.log.info('mergeImagesIntoOnePdf works with outputFormat "pdf" only; skipped.')
            elif merge_images and len(image_inputs) > 1:
                dest = os.path.join(tmp, 'merged.pdf')
                pages = await asyncio.to_thread(images_to_one_pdf, image_inputs, dest, max_width)
                with open(dest, 'rb') as f:
                    await store.set_value('merged.pdf', f.read(), content_type='application/pdf')
                await Actor.push_data({'url': None, 'merged': True, 'count': pages,
                                       'files': [{'key': 'merged.pdf', 'url': await store.get_public_url('merged.pdf'),
                                                  'bytes': os.path.getsize(dest)}]})
            if make_zip and all_outputs:
                dest = os.path.join(tmp, 'all-files.zip')
                with zipfile.ZipFile(dest, 'w', zipfile.ZIP_DEFLATED) as z:
                    for p in all_outputs:
                        z.write(p, os.path.basename(p))
                with open(dest, 'rb') as f:
                    await store.set_value('all-files.zip', f.read(), content_type='application/zip')
                await Actor.push_data({'url': None, 'zip': True, 'count': len(all_outputs),
                                       'files': [{'key': 'all-files.zip',
                                                  'url': await store.get_public_url('all-files.zip'),
                                                  'bytes': os.path.getsize(dest)}]})
        await Actor.set_status_message(f'Converted {ok} file(s), failed {failed}.')
