FROM apify/actor-python:3.12

USER root
# LibreOffice (Writer, Calc, Impress, Draw) and metric-compatible fonts so Office layouts keep their line breaks:
# Carlito = Calibri, Caladea = Cambria, Liberation = Arial/Times/Courier; DejaVu and Noto cover Cyrillic and more
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      libreoffice-writer-nogui libreoffice-calc-nogui libreoffice-impress-nogui libreoffice-draw-nogui \
      fonts-crosextra-carlito fonts-crosextra-caladea fonts-liberation fonts-liberation2 fonts-dejavu-core \
      fonts-noto-core \
 && rm -rf /var/lib/apt/lists/*
USER myuser

COPY --chown=myuser:myuser requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=myuser:myuser . ./
RUN python -m compileall -q src/

CMD ["python", "-m", "src"]
