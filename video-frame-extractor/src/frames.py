"""Frame extraction with ffmpeg: every N seconds, N evenly spaced, exact timestamps, scene changes or keyframes."""
from __future__ import annotations

import json
import math
import os
import re
import subprocess

from PIL import Image, ImageDraw, ImageFont

FORMATS = {'jpg': ('jpg', ['-q:v', '3']), 'png': ('png', []), 'webp': ('webp', ['-c:v', 'libwebp', '-quality', '85'])}
FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'


class FrameError(Exception):
    pass


def _run(cmd: list[str], timeout: int = 600) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise FrameError('ffmpeg took too long on this video') from e


def probe(path: str) -> dict:
    p = _run(['ffprobe', '-v', 'error', '-print_format', 'json', '-show_format', '-show_streams', path], 120)
    try:
        info = json.loads(p.stdout or '{}')
    except json.JSONDecodeError:
        info = {}
    video = next((s for s in info.get('streams', []) if s.get('codec_type') == 'video'
                  and not (s.get('disposition') or {}).get('attached_pic')), None)
    if not video:
        raise FrameError('the file has no video stream')
    duration = float(info.get('format', {}).get('duration') or video.get('duration') or 0)
    num, _, den = str(video.get('avg_frame_rate') or '0/1').partition('/')
    fps = float(num) / float(den or 1) if float(den or 1) else 0.0
    return {'duration': round(duration, 3), 'width': video.get('width'), 'height': video.get('height'),
            'fps': round(fps, 3), 'codec': video.get('codec_name'),
            'formatName': info.get('format', {}).get('format_name')}


def parse_time(s: str) -> float:
    s = s.strip()
    if not re.fullmatch(r'(\d+:){0,2}\d+(\.\d+)?', s):
        raise FrameError(f'bad timestamp "{s}" (use seconds like 90.5 or hh:mm:ss)')
    secs = 0.0
    for part in s.split(':'):
        secs = secs * 60 + float(part)
    return secs


def plan_times(mode: str, duration: float, *, interval: float, count: int, timestamps: list[str],
               max_frames: int) -> list[float]:
    if duration <= 0 and mode != 'timestamps':
        raise FrameError('the video duration is unknown; use mode "timestamps"')
    if mode == 'interval':
        n = min(max_frames, int(math.floor(duration / interval)) + 1)
        times = [i * interval for i in range(n)]
    elif mode == 'count':
        n = min(max_frames, count)
        times = [(i + 0.5) * duration / n for i in range(n)]
    elif mode == 'timestamps':
        times = [parse_time(t) for t in timestamps][:max_frames]
        if duration > 0:
            times = [t for t in times if t < duration]
    else:
        raise FrameError(f'unknown mode "{mode}"')
    # The very last frame of a file is often not decodable at its exact time
    return [min(t, max(duration - 0.05, 0)) if duration > 0 else t for t in times]


def _scale(max_width: int) -> list[str]:
    return ['-vf', f"scale='min({max_width},iw)':-2"] if max_width else []


def grab(path: str, t: float, dest: str, fmt: str, max_width: int) -> bool:
    _, opts = FORMATS[fmt]
    p = _run(['ffmpeg', '-v', 'error', '-y', '-ss', f'{t:.3f}', '-i', path, '-frames:v', '1', *_scale(max_width),
              *opts, '-f', 'image2', '-update', '1', dest], 120)
    return p.returncode == 0 and os.path.exists(dest) and os.path.getsize(dest) > 0


def select_frames(path: str, outdir: str, stem: str, fmt: str, max_width: int, mode: str,
                  threshold: float, max_frames: int) -> list[tuple[float, str]]:
    """Scene changes or keyframes in one ffmpeg pass. Returns [(time, file)]."""
    ext, opts = FORMATS[fmt]
    pattern = os.path.join(outdir, f'{stem}-sel%05d.{ext}')
    # Scenes: the first frame opens the first scene, then every frame that differs enough from the previous one
    filters = ([f"select='eq(n\\,0)+gt(scene\\,{threshold})'"] if mode == 'scenes' else []) + ['showinfo']
    if max_width:
        filters.append(f"scale='min({max_width},iw)':-2")
    pre = ['-skip_frame', 'nokey'] if mode == 'keyframes' else []
    p = _run(['ffmpeg', '-v', 'info', '-y', *pre, '-i', path, '-vf', ','.join(filters), '-fps_mode', 'vfr',
              '-frames:v', str(max_frames), *opts, '-f', 'image2', pattern], 1800)
    if p.returncode != 0:
        raise FrameError('ffmpeg could not decode the video: ' + (p.stderr.strip().splitlines() or ['?'])[-1][:200])
    times = [float(m) for m in re.findall(r'pts_time:\s*([0-9.]+)', p.stderr)]
    files = sorted(f for f in os.listdir(outdir) if f.startswith(f'{stem}-sel'))
    return [(round(t, 3), os.path.join(outdir, f)) for t, f in zip(times, files)]


def timecode(t: float) -> str:
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f'{int(h):02d}:{int(m):02d}:{s:06.3f}'


def contact_sheet(frames: list[tuple[float, str]], dest: str, columns: int = 4, thumb_width: int = 320) -> None:
    font = ImageFont.truetype(FONT, 16)
    thumbs = []
    for t, f in frames:
        with Image.open(f) as im:
            im = im.convert('RGB')
            im.thumbnail((thumb_width, thumb_width * 4))
            thumbs.append((t, im.copy()))
    th = max(im.height for _, im in thumbs)
    rows = math.ceil(len(thumbs) / columns)
    sheet = Image.new('RGB', (columns * (thumb_width + 8) + 8, rows * (th + 8) + 8), (24, 24, 24))
    draw = ImageDraw.Draw(sheet)
    for i, (t, im) in enumerate(thumbs):
        x, y = 8 + (i % columns) * (thumb_width + 8), 8 + (i // columns) * (th + 8)
        sheet.paste(im, (x, y))
        label = timecode(t)[:-4]
        w = draw.textlength(label, font=font)
        draw.rectangle([x + 4, y + im.height - 26, x + 12 + w, y + im.height - 4], fill=(0, 0, 0))
        draw.text((x + 8, y + im.height - 25), label, font=font, fill='white')
    sheet.save(dest, quality=85)
