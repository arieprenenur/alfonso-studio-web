FROM python:3.11-slim

WORKDIR /app

# Install FFmpeg
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements dan install
COPY requirements.txt .

# Install dengan retry
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt || \
    pip install --no-cache-dir Flask==2.3.3 gunicorn==21.2.0 yt-dlp==2023.12.30 requests==2.31.0 Werkzeug==2.3.8

# Copy semua file
COPY . .

# Jalankan aplikasi
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:8080"]
