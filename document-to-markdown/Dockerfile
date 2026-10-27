FROM apify/actor-python:3.12

USER root
# LibreOffice for legacy Office formats, Tesseract with common languages for OCR, fonts with Cyrillic
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      libreoffice-writer-nogui libreoffice-calc-nogui libreoffice-impress-nogui \
      tesseract-ocr tesseract-ocr-eng tesseract-ocr-ukr tesseract-ocr-rus tesseract-ocr-deu tesseract-ocr-fra \
      tesseract-ocr-spa tesseract-ocr-ita tesseract-ocr-por tesseract-ocr-pol tesseract-ocr-nld tesseract-ocr-ces \
      fonts-dejavu-core fonts-liberation \
 && rm -rf /var/lib/apt/lists/*
USER myuser

COPY --chown=myuser:myuser requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=myuser:myuser . ./
RUN python -m compileall -q src/

CMD ["python", "-m", "src"]
