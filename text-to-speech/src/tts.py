"""Text to speech with Piper: sentence-by-sentence synthesis, MP3/WAV/OGG encoding and SRT/VTT subtitles."""
from __future__ import annotations

import html
import io
import json
import os
import re
import subprocess
import urllib.request
import wave
import zipfile
from html.parser import HTMLParser

import onnxruntime
from piper import PiperVoice, SynthesisConfig
from piper.config import PiperConfig

HF = 'https://huggingface.co/rhasspy/piper-voices/resolve/main/'
# Only voices whose training data allows commercial use (CC0, public domain, Apache 2.0, CC BY 4.0).
# uk_UA-ukrainian_tts is left out: its character-based model skips capital letters and digits.
VOICES = {
    'uk_UA-tetiana-high': ('Ukrainian', 'Apache-2.0'),
    'uk_UA-mykyta-high': ('Ukrainian', 'Apache-2.0'),
    'uk_UA-oleksa-high': ('Ukrainian', 'Apache-2.0'),
    'en_US-ljspeech-high': ('English (US)', 'public domain'),
    'en_US-john-medium': ('English (US)', 'public domain'),
    'en_US-kristin-medium': ('English (US)', 'public domain'),
    'en_US-bryce-medium': ('English (US)', 'public domain'),
    'en_US-norman-medium': ('English (US)', 'public domain'),
    'en_US-joe-medium': ('English (US)', 'CC0'),
    'en_GB-cori-high': ('English (UK)', 'public domain'),
    'en_GB-alba-medium': ('English (UK)', 'CC BY 4.0'),
    'de_DE-thorsten-high': ('German', 'CC0'),
    'de_DE-kerstin-low': ('German', 'CC0'),
    'fr_FR-siwis-medium': ('French', 'CC BY 4.0'),
    'fr_FR-gilles-low': ('French', 'CC0'),
    'es_ES-davefx-medium': ('Spanish (Spain)', 'CC0'),
    'es_MX-claude-high': ('Spanish (Mexico)', 'Apache-2.0'),
    'it_IT-serena-high': ('Italian', 'CC BY 4.0'),
    'pl_PL-gosia-medium': ('Polish', 'CC0'),
    'pl_PL-darkman-medium': ('Polish', 'CC0'),
    'pt_BR-faber-medium': ('Portuguese (Brazil)', 'CC0'),
    'nl_NL-pim-medium': ('Dutch', 'CC0'),
    'cs_CZ-jirka-medium': ('Czech', 'CC0'),
    'ru_RU-denis-medium': ('Russian', 'CC0'),
    'ru_RU-dmitri-medium': ('Russian', 'CC0'),
    'ro_RO-mihai-medium': ('Romanian', 'CC0'),
    'fi_FI-harri-medium': ('Finnish', 'CC0'),
    'hu_HU-anna-medium': ('Hungarian', 'CC0'),
    'sk_SK-lili-medium': ('Slovak', 'CC0'),
    'sv_SE-nst-medium': ('Swedish', 'CC0'),
    'da_DK-talesyntese-medium': ('Danish', 'CC0'),
    'el_GR-rapunzelina-medium': ('Greek', 'CC0'),
    'lv_LV-aivars-medium': ('Latvian', 'CC0'),
    'sl_SI-artur-medium': ('Slovenian', 'CC BY 4.0'),
    'zh_CN-chaowen-medium': ('Chinese', 'CC0'),
    'fa_IR-amir-medium': ('Persian', 'CC0'),
    'vi_VN-vais1000-medium': ('Vietnamese', 'CC BY 4.0'),
}
SENTENCE_PAUSE = 0.25
PARAGRAPH_PAUSE = 0.7
MAX_SENTENCE_CHARS = 400


class TtsError(Exception):
    pass


def voice_path(voice: str) -> str:
    lang, name, quality = voice.split('-', 2)
    return f'{lang.split("_")[0]}/{lang}/{name}/{quality}/{voice}'


def load_voice(voice: str, cache_dir: str) -> PiperVoice:
    if voice not in VOICES:
        raise TtsError(f'unknown voice "{voice}"')
    os.makedirs(cache_dir, exist_ok=True)
    model = os.path.join(cache_dir, voice + '.onnx')
    for suffix in ('.onnx.json', '.onnx'):
        dest = model[:-5] + suffix
        if not os.path.exists(dest):
            url = HF + urllib.request.quote(voice_path(voice)) + suffix
            try:
                with urllib.request.urlopen(url, timeout=300) as r, open(dest + '.part', 'wb') as f:
                    while chunk := r.read(1 << 20):
                        f.write(chunk)
            except OSError as e:
                raise TtsError(f'could not download voice {voice}: {e}') from e
            os.replace(dest + '.part', dest)
    # onnxruntime would start a thread per host CPU; on Apify a run gets one core per 4 GB of memory, and extra
    # threads only fight over it (measured: 10x slower)
    memory = int(os.environ.get('ACTOR_MEMORY_MBYTES') or os.environ.get('APIFY_MEMORY_MBYTES') or 0)
    threads = max(1, memory // 4096) if memory else (os.cpu_count() or 1)
    opts = onnxruntime.SessionOptions()
    opts.intra_op_num_threads = threads
    opts.inter_op_num_threads = 1
    with open(model + '.json', encoding='utf-8') as f:
        config = PiperConfig.from_dict(json.load(f))
    session = onnxruntime.InferenceSession(model, sess_options=opts, providers=['CPUExecutionProvider'])
    return PiperVoice(session=session, config=config)


class _Text(HTMLParser):
    BLOCK = {'p', 'div', 'br', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'tr', 'section', 'article', 'blockquote'}
    SKIP = {'script', 'style', 'noscript', 'nav', 'footer', 'header', 'svg'}

    def __init__(self):
        super().__init__()
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        self.skip += tag in self.SKIP
        if tag in self.BLOCK:
            self.parts.append('\n\n')

    def handle_endtag(self, tag):
        self.skip -= tag in self.SKIP and self.skip > 0
        if tag in self.BLOCK:
            self.parts.append('\n\n')

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def extract_text(path: str, name: str, ctype: str) -> str:
    """Plain text from TXT, Markdown, HTML, PDF or DOCX."""
    with open(path, 'rb') as f:
        head = f.read(8)
    ext = os.path.splitext(name or '')[1].lower()
    if head.startswith(b'%PDF'):
        import pypdfium2 as pdfium
        try:
            pdf = pdfium.PdfDocument(path)
        except pdfium.PdfiumError as e:
            raise TtsError('the PDF is damaged or password-protected') from e
        text = '\n\n'.join(p.get_textpage().get_text_range() for p in pdf)
        pdf.close()
        if len(text.strip()) < 20:
            raise TtsError('the PDF has no text layer (scanned?) — OCR it first')
        # Lines inside a paragraph are joined; blank lines and lines ending a sentence keep breaks
        return re.sub(r'(?<![.!?:;\n])\r?\n(?!\s*\n)', ' ', text)
    if head.startswith(b'PK') and (ext == '.docx' or 'officedocument' in ctype):
        try:
            with zipfile.ZipFile(path) as z:
                xml = z.read('word/document.xml').decode('utf-8', 'replace')
        except (zipfile.BadZipFile, KeyError) as e:
            raise TtsError('the DOCX file is damaged') from e
        paras = re.findall(r'<w:p[ >].*?</w:p>', xml, re.S)
        return '\n\n'.join(html.unescape(''.join(re.findall(r'<w:t[^>]*>([^<]*)</w:t>', p))) for p in paras)
    raw = open(path, 'rb').read()
    if b'\x00' in raw[:4096]:
        raise TtsError('unsupported file: use TXT, Markdown, HTML, PDF or DOCX')
    text = raw.decode('utf-8', 'replace')
    if ext in ('.html', '.htm') or 'html' in ctype or re.search(r'<(html|body|p|div)\b', text[:2000], re.I):
        parser = _Text()
        parser.feed(text)
        return html.unescape(''.join(parser.parts))
    if ext in ('.md', '.markdown') or 'markdown' in ctype:
        text = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', text)  # images
        text = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', text)  # links -> text
        text = re.sub(r'^\s{0,3}(#{1,6}|[-*+]|\d+\.)\s+', '', text, flags=re.M)
        text = re.sub(r'[*_`~>|]+', '', text)
    return text


def split_text(text: str, max_chars: int) -> tuple[list[list[str]], int, bool]:
    """Paragraphs of sentences; returns (paragraphs, characters used, truncated)."""
    text = text.replace('\r', '')
    paras, used, truncated = [], 0, False
    for block in re.split(r'\n\s*\n', text):
        block = re.sub(r'\s+', ' ', block).strip()
        if not block:
            continue
        sentences = []
        for s in re.split(r'(?<=[.!?…。！？])\s+', block):
            while len(s) > MAX_SENTENCE_CHARS:  # very long sentences are cut at a comma or space
                cut = max(s.rfind(', ', 0, MAX_SENTENCE_CHARS), s.rfind(' ', 0, MAX_SENTENCE_CHARS))
                cut = cut if cut > 50 else MAX_SENTENCE_CHARS
                sentences.append(s[:cut + 1].strip())
                s = s[cut + 1:].strip()
            if s:
                sentences.append(s)
        kept = []
        for s in sentences:
            if used + len(s) > max_chars:
                truncated = True
                break
            kept.append(s)
            used += len(s)
        if kept:
            paras.append(kept)
        if truncated:
            break
    return paras, used, truncated


# espeak reads quotation marks aloud in some languages («відкриті лапки»); they carry no sound
QUOTES = re.compile('[«»“”„‟"]')


def synthesize(voice: PiperVoice, paras: list[list[str]], speed: float, speaker: int | None = None,
               ukrainian: bool = False) -> tuple[bytes, int, list[tuple[float, float, str]]]:
    """Returns (16-bit mono PCM, sample rate, cues [(start, end, sentence)]).
    ukrainian=True puts the word stress from a dictionary (espeak often stresses Ukrainian words wrongly)."""
    cfg = SynthesisConfig(length_scale=1 / speed, speaker_id=speaker)
    rate = voice.config.sample_rate
    pcm, cues, t = bytearray(), [], 0.0
    for pi, sentences in enumerate(paras):
        for si, s in enumerate(sentences):
            spoken = QUOTES.sub('', s)
            if ukrainian:
                from .uk_stress import synthesize_uk
                audio, _ = synthesize_uk(voice, spoken, cfg)
            else:
                audio = b''.join(c.audio_int16_bytes for c in voice.synthesize(spoken, cfg))
            if not audio:
                continue
            dur = len(audio) / 2 / rate
            cues.append((round(t, 3), round(t + dur, 3), s))
            pcm += audio
            pause = (SENTENCE_PAUSE if si < len(sentences) - 1 else PARAGRAPH_PAUSE if pi < len(paras) - 1 else 0) / speed
            pcm += b'\x00\x00' * int(pause * rate)
            t += dur + pause
    return bytes(pcm), rate, cues


def encode(pcm: bytes, rate: int, fmt: str, dest: str, bitrate: str = '64k') -> None:
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    if fmt == 'wav':
        with open(dest, 'wb') as f:
            f.write(buf.getvalue())
        return
    codec = {'mp3': ['-c:a', 'libmp3lame', '-b:a', bitrate], 'ogg': ['-c:a', 'libopus', '-b:a', bitrate]}[fmt]
    p = subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'wav', '-i', 'pipe:0', *codec, dest],
                       input=buf.getvalue(), capture_output=True, timeout=900)
    if p.returncode != 0:
        raise TtsError('audio encoding failed: ' + p.stderr.decode('utf-8', 'replace')[-200:])


def _ts(t: float, sep: str) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f'{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}'


def to_srt(cues) -> str:
    return '\n'.join(f'{i}\n{_ts(a, ",")} --> {_ts(b, ",")}\n{t}\n' for i, (a, b, t) in enumerate(cues, 1))


def to_vtt(cues) -> str:
    return 'WEBVTT\n\n' + '\n'.join(f'{_ts(a, ".")} --> {_ts(b, ".")}\n{t}\n' for a, b, t in cues)
