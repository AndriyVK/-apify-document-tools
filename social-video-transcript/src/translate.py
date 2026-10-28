"""Transcript segments -> another language with a Groq-hosted LLM (qwen3.8-27b without reasoning: chosen for the
Perekladach voice-over on 28.10.2026 as the fastest model with good Ukrainian and Russian)."""
from __future__ import annotations

import json
import os
import re
import time

import httpx

CHAT_URL = 'https://api.groq.com/openai/v1/chat/completions'
MODEL = os.environ.get('TRANSLATE_MODEL', 'qwen/qwen3.8-27b')
BATCH = 40           # segments per request: keeps answers short enough to stay reliable
MAX_RETRIES = 5

LANGUAGES = {'en': 'English', 'uk': 'Ukrainian', 'ru': 'Russian', 'de': 'German', 'fr': 'French', 'es': 'Spanish',
             'pt': 'Portuguese', 'it': 'Italian', 'pl': 'Polish', 'nl': 'Dutch', 'tr': 'Turkish', 'cs': 'Czech',
             'ro': 'Romanian', 'sv': 'Swedish', 'ar': 'Arabic', 'hi': 'Hindi', 'id': 'Indonesian', 'vi': 'Vietnamese',
             'zh': 'Chinese (Simplified)', 'ja': 'Japanese', 'ko': 'Korean'}


class TranslationError(Exception):
    pass


def _headers() -> dict:
    h = {'Content-Type': 'application/json'}
    if os.environ.get('GROQ_API_KEY'):  # on Apify; locally a proxy may add the header instead
        h['Authorization'] = 'Bearer ' + os.environ['GROQ_API_KEY']
    return h


def _chat(client: httpx.Client, prompt: str) -> str:
    body = {'model': MODEL, 'temperature': 0.2, 'messages': [{'role': 'user', 'content': prompt}]}
    if 'qwen' in MODEL:
        body['reasoning_effort'] = 'none'  # qwen thinks aloud by default: slow and costly
    for attempt in range(MAX_RETRIES):
        r = client.post(CHAT_URL, json=body, headers=_headers())
        if r.status_code == 200:
            return r.json()['choices'][0]['message']['content']
        if r.status_code in (429, 500, 502, 503, 504) and attempt < MAX_RETRIES - 1:
            try:
                wait = float(r.headers.get('retry-after') or 0)
            except ValueError:
                wait = 0
            if wait > 300 or 'per day' in r.text:
                raise TranslationError('the translation service is at its usage limit right now; try again later')
            time.sleep(wait or min(30, 3 * 2 ** attempt))
            continue
        if r.status_code in (401, 403):
            raise TranslationError('translation service authorisation failed (Actor configuration problem)')
        raise TranslationError(f'translation service error HTTP {r.status_code}')
    raise TranslationError('the translation service did not respond, try again later')


def _json_array(text: str, n: int) -> list[str] | None:
    m = re.search(r'\[.*\]', text, re.S)
    if not m:
        return None
    try:
        arr = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(arr, list) or len(arr) != n:
        return None
    return [str(a).strip() for a in arr]


def translate(segments: list[dict], target: str) -> list[dict]:
    """Same segments (start, end) with the text in the target language."""
    lang = LANGUAGES[target]
    out = []
    with httpx.Client(timeout=httpx.Timeout(120, connect=20)) as client:
        for i in range(0, len(segments), BATCH):
            part = segments[i:i + BATCH]
            context = ' '.join(s['text'] for s in segments[max(0, i - 3):i])
            prompt = (f'Translate each line of this video transcript into natural {lang}. The lines are consecutive '
                      'fragments of speech: keep the meaning, keep names, do not merge, split or skip lines, keep the '
                      'same number of lines. '
                      + (f'Previous lines for context (do not translate): {context}\n' if context else '')
                      + 'Return only a JSON array of strings, one per line, same order.\n\n'
                      + json.dumps([s['text'] for s in part], ensure_ascii=False))
            arr = None
            for _ in range(3):
                arr = _json_array(_chat(client, prompt), len(part))
                if arr:
                    break
            if not arr:
                raise TranslationError('translation failed: the model returned a malformed answer')
            out += [{**s, 'text': t or s['text']} for s, t in zip(part, arr)]
    return out
