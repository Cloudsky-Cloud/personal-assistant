FROM python:3.12-slim AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml .
RUN pip install --upgrade pip setuptools
RUN pip install --no-cache-dir -e ".[dev]"

# Pre-download Whisper base model so cold starts are fast
RUN python -c "\
from faster_whisper import WhisperModel; \
WhisperModel('base', device='cpu', compute_type='int8', download_root='/app/data/whisper')"

COPY . .

CMD ["python", "-m", "src.main"]
