"""Apify Actor: extract still frames from videos (ffmpeg) with timecodes, metadata and a contact sheet."""
from __future__ import annotations

import asyncio
import math
import mimetypes
import os
import re
import tempfile

import httpx
from apify import Actor

from .download import DownloadError, download
from .frames import (FORMATS, FrameError, contact_sheet, grab, is_blank, plan_times, probe, select_frames,
                     timecode, window)

EVENT_FRAME = 'frame'
EVENT_SCENE_MINUTE = 'scene-minute'  # scene detection decodes the whole video
MODES = ('count', 'interval', 'timestamps', 'scenes', 'keyframes')


def _sources(inp: dict) -> list[str]:
    urls = []
    for item in inp.get('sources') or []:
        url = item.get('url') if isinstance(item, dict) else item
        if isinstance(url, str) and url.strip():
            urls.append(url.strip())
    return urls


def _stem(name: str, idx: int) -> str:
    stem = re.sub(r'[^A-Za-z0-9._-]+', '-', os.path.splitext(name or '')[0]).strip('-.')[:50]
    return f'{idx:04d}-{stem or "video"}'


async def main() -> None:
    async with Actor:
        inp = await Actor.get_input() or {}
        urls = _sources(inp)
        if not urls:
            await Actor.fail(status_message='Input "sources" is empty: add at least one video URL.')
            return
        mode = str(inp.get('mode') or 'count')
        fmt = str(inp.get('format') or 'jpg').lower()
        if mode not in MODES or fmt not in FORMATS:
            await Actor.fail(status_message=f'mode must be one of {", ".join(MODES)}; format one of jpg, png, webp.')
            return
        interval = max(float(inp.get('intervalSeconds') or 10), 0.1)
        count = min(max(int(inp.get('frameCount') or 10), 1), 2000)
        stamps = [str(t) for t in (inp.get('timestamps') or []) if str(t).strip()]
        threshold = min(max(float(inp.get('sceneThreshold') or 0.3), 0.01), 1.0)
        max_frames = min(max(int(inp.get('maxFramesPerVideo') or 100), 1), 2000)
        max_width = int(inp.get('maxWidth') or 0)
        sheet = bool(inp.get('contactSheet', True))
        start_in, end_in = inp.get('startTime'), inp.get('endTime')
        skip_blank = bool(inp.get('skipBlankFrames', False))
        if mode == 'timestamps' and not stamps:
            await Actor.fail(status_message='mode "timestamps" needs a list of timestamps.')
            return

        charging = Actor.get_charging_manager()
        store = await Actor.open_key_value_store()
        ok = failed = total_frames = 0
        with tempfile.TemporaryDirectory() as tmp:
            async with httpx.AsyncClient(timeout=httpx.Timeout(300, connect=20),
                                         headers={'User-Agent': 'video-frame-extractor (Apify Actor)'}) as client:
                for idx, url in enumerate(urls, 1):
                    left = charging.calculate_max_event_charge_count_within_limit(EVENT_FRAME)
                    if left == 0:
                        Actor.log.warning('Maximum charge per run reached, remaining videos were skipped.')
                        break
                    limit = max_frames if left is None else min(max_frames, left)
                    src = os.path.join(tmp, f'in-{idx:04d}')
                    outdir = os.path.join(tmp, f'out-{idx:04d}')
                    os.makedirs(outdir)
                    try:
                        name, _ = await download(client, url, src)
                        stem = _stem(name, idx)
                        meta = await asyncio.to_thread(probe, src)
                        ext, _ = FORMATS[fmt]
                        t0, t1 = window(meta['duration'], start_in, end_in)
                        skipped = 0
                        if mode in ('scenes', 'keyframes'):
                            got = await asyncio.to_thread(select_frames, src, outdir, stem, fmt, max_width, mode,
                                                          threshold, limit, t0, t1)
                            if skip_blank:
                                kept = [(t, f) for t, f in got if not is_blank(f)]
                                skipped, got = len(got) - len(kept), kept
                        else:
                            times = plan_times(mode, meta['duration'], interval=interval, count=count,
                                               timestamps=stamps, max_frames=limit, start=t0, end=t1)
                            got = []
                            for n, t in enumerate(times, 1):
                                dest = os.path.join(outdir, f'{stem}-{n:05d}.{ext}')
                                if not await asyncio.to_thread(grab, src, t, dest, fmt, max_width):
                                    continue
                                if skip_blank and is_blank(dest):
                                    # a fade or a black gap: try a little later, inside the window, once
                                    t2 = min(t + 0.7, (t1 if t1 != math.inf else t + 0.7) - 0.05)
                                    ok2 = t2 > t and await asyncio.to_thread(grab, src, t2, dest, fmt, max_width)
                                    if not ok2 or is_blank(dest):
                                        skipped += 1
                                        continue
                                    t = t2
                                got.append((round(t, 3), dest))
                        if not got:
                            raise FrameError('no frames could be extracted (check the timestamps or the threshold)')
                    except (DownloadError, FrameError, httpx.HTTPError) as e:
                        failed += 1
                        await Actor.push_data({'url': url, 'error': str(e) or type(e).__name__})
                        continue
                    frames = []
                    for n, (t, path) in enumerate(got, 1):
                        key = f'{stem}-{n:05d}.{ext}'
                        with open(path, 'rb') as f:
                            await store.set_value(key, f.read(), content_type=mimetypes.guess_type(path)[0])
                        frames.append({'index': n, 'time': t, 'timecode': timecode(t), 'key': key,
                                       'url': await store.get_public_url(key), 'bytes': os.path.getsize(path)})
                    item = {'url': url, 'fileName': name or None, 'mode': mode, **meta,
                            'frameCount': len(frames), 'frames': frames}
                    if start_in not in (None, '') or end_in not in (None, ''):
                        item['window'] = {'start': t0, 'end': None if t1 == math.inf else round(t1, 3)}
                    if skip_blank:
                        item['blankFramesSkipped'] = skipped
                    if sheet:
                        key = f'{stem}-contact-sheet.jpg'
                        dest = os.path.join(tmp, key)
                        await asyncio.to_thread(contact_sheet, got, dest)
                        with open(dest, 'rb') as f:
                            await store.set_value(key, f.read(), content_type='image/jpeg')
                        item['contactSheetUrl'] = await store.get_public_url(key)
                    await Actor.push_data(item)
                    # One event per extracted frame, after the files are saved; the contact sheet is free
                    await Actor.charge(EVENT_FRAME, count=len(frames))
                    if mode == 'scenes':
                        span = (min(t1, meta['duration']) if t1 != math.inf else meta['duration']) - t0
                        await Actor.charge(EVENT_SCENE_MINUTE, count=max(1, math.ceil(span / 60)))
                    total_frames += len(frames)
                    ok += 1
        await Actor.set_status_message(f'Extracted {total_frames} frame(s) from {ok} video(s), failed {failed}.')
