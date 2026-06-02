FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install yt-dlp (latest)
RUN curl -sL https://github.com/yt-dlp/yt-dlp/releases/download/latest/yt-dlp -o /usr/local/bin/yt-dlp \
    && chmod a+rx /usr/local/bin/yt-dlp

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create transcript venv at build time
RUN python -m venv /opt/content-short/transcript-venv && \
    /opt/content-short/transcript-venv/bin/pip install --no-cache-dir -U pip wheel "setuptools<82" && \
    /opt/content-short/transcript-venv/bin/pip install --no-cache-dir youtube-transcript-api

# Copy application files
COPY . .

# Create storage directory
RUN mkdir -p /app/storage/free-viral-shorts /app/storage/transcripts /app/storage/video /app/storage/api-jobs

# Expose port
EXPOSE 8080

# Environment defaults
ENV FFMPEG_BIN=/usr/bin/ffmpeg
ENV CV_PYTHON_BIN=/usr/local/bin/python
ENV CONTENT_SHORT_API_TOKEN=change-me
ENV CONTENT_SHORT_BASE_URL=http://content-short-api:8080
ENV VENV_DIR=/opt/content-short/transcript-venv
ENV SKIP_INSTALL=1

CMD ["uvicorn", "api_server:app", "--host", "0.0.0.0", "--port", "8080"]
