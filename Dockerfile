# ==============================================================================
# Intelligent Tracker - Multi-Arch Default Dockerfile
# Supports cross-compilation for amd64 and arm64 via docker buildx
# ==============================================================================

FROM python:3.12-slim-bookworm AS builder

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    git \
    pkg-config \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir --prefix=/install -r requirements.txt

# ------------------------------------------------------------------------------
# Runtime Stage
# ------------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/install/bin:$PATH" \
    PYTHONPATH="/install/lib/python3.12/site-packages:$PYTHONPATH" \
    MPLBACKEND="Agg"

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    ffmpeg \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /install

WORKDIR /app
RUN useradd -m -u 1000 tracker && \
    mkdir -p /app/data /app/models /app/configs && \
    chown -R tracker:tracker /app

COPY --chown=tracker:tracker . /app

USER tracker

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/status || exit 1

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "dashboard.app:app", "--host", "0.0.0.0", "--port", "8000"]
