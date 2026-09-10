FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    XDG_CACHE_HOME=/tmp/briefly-cache \
    HF_HOME=/tmp/briefly-models

WORKDIR /app
COPY requirements.txt requirements-whisper.txt ./
ARG INSTALL_WHISPER=false
RUN python -m pip install --no-cache-dir -r requirements.txt \
    && if [ "$INSTALL_WHISPER" = "true" ]; then python -m pip install --no-cache-dir -r requirements-whisper.txt; fi \
    && useradd --create-home --uid 10001 briefly

COPY --chown=briefly:briefly app.py alembic.ini ./
COPY --chown=briefly:briefly briefly ./briefly
COPY --chown=briefly:briefly migrations ./migrations
COPY --chown=briefly:briefly assets ./assets
COPY --chown=briefly:briefly .streamlit/config.toml ./.streamlit/config.toml

RUN mkdir -p /app/data && chown briefly:briefly /app /app/data
USER briefly
EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=4)"
CMD ["python", "-m", "streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true", "--browser.gatherUsageStats=false"]
