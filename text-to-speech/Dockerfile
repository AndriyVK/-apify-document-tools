FROM apify/actor-python:3.12

USER root
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*
USER myuser

# CPU-only torch for the Ukrainian stress tagger (stanza); the default wheel would pull in CUDA (~2 GB)
RUN pip install --no-cache-dir torch==2.14.1 --index-url https://download.pytorch.org/whl/cpu
COPY --chown=myuser:myuser requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=myuser:myuser . ./
RUN python -m compileall -q src/
# The default voices and the Ukrainian stress models are baked into the image; other voices download on first use
RUN python -c "from src.tts import load_voice; [load_voice(v, 'voices') for v in ('en_US-john-medium', 'uk_UA-tetiana-high', 'uk_UA-mykyta-high')]" \
 && python -c "from ukrainian_word_stress import Stressifier; print(Stressifier()('Перевірка наголосу.'))"

CMD ["python", "-m", "src"]
