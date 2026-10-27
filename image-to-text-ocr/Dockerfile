FROM apify/actor-python:3.12

USER root
# Tesseract with 38 languages
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr \
      tesseract-ocr-eng tesseract-ocr-ukr tesseract-ocr-rus tesseract-ocr-deu tesseract-ocr-fra tesseract-ocr-spa \
      tesseract-ocr-ita tesseract-ocr-por tesseract-ocr-pol tesseract-ocr-nld tesseract-ocr-ces tesseract-ocr-slk \
      tesseract-ocr-tur tesseract-ocr-ron tesseract-ocr-hun tesseract-ocr-bul tesseract-ocr-ell tesseract-ocr-swe \
      tesseract-ocr-nor tesseract-ocr-dan tesseract-ocr-fin tesseract-ocr-lit tesseract-ocr-lav tesseract-ocr-est \
      tesseract-ocr-hrv tesseract-ocr-srp tesseract-ocr-slv tesseract-ocr-bel tesseract-ocr-kaz tesseract-ocr-vie \
      tesseract-ocr-ind tesseract-ocr-heb tesseract-ocr-ara tesseract-ocr-hin tesseract-ocr-chi-sim \
      tesseract-ocr-chi-tra tesseract-ocr-jpn tesseract-ocr-kor \
 && rm -rf /var/lib/apt/lists/*
USER myuser

COPY --chown=myuser:myuser requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=myuser:myuser . ./
RUN python -m compileall -q src/

CMD ["python", "-m", "src"]
