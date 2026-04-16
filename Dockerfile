# Stage 1: Build Stage
FROM python:3.13-slim AS builder

# Install build dependencies (for av and other packages)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libavformat-dev \
    libavcodec-dev \
    libavdevice-dev \
    libavutil-dev \
    libavfilter-dev \
    libswscale-dev \
    libswresample-dev \
    pkg-config \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir cython && \
    pip install --no-cache-dir -r requirements.txt

# Stage 2: Final Stage
FROM python:3.13-slim

# Install runtime dependencies (only ffmpeg, no dev packages)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy installed packages from builder stage
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages

COPY . .

EXPOSE 8000

CMD uvicorn main:app --host 0.0.0.0 --port 8000
