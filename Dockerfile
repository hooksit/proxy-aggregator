FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DEBIAN_FRONTEND=noninteractive \
    TZ=Europe/Moscow

WORKDIR /app

# Install system dependencies & curl to fetch sing-box
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    tar \
    tzdata \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

# Install official sing-box binary (v1.11.4 or latest stable)
ARG TARGETARCH
RUN set -eux; \
    ARCH="$(dpkg --print-architecture)"; \
    case "${ARCH}" in \
        amd64) SB_ARCH="linux-amd64" ;; \
        arm64) SB_ARCH="linux-arm64" ;; \
        *) echo "Unsupported arch: ${ARCH}"; exit 1 ;; \
    esac; \
    SB_VER="1.11.4"; \
    curl -fsSL "https://github.com/SagerNet/sing-box/releases/download/v${SB_VER}/sing-box-${SB_VER}-${SB_ARCH}.tar.gz" -o sing-box.tar.gz; \
    tar -xzf sing-box.tar.gz; \
    mv "sing-box-${SB_VER}-${SB_ARCH}/sing-box" /usr/local/bin/sing-box; \
    chmod +x /usr/local/bin/sing-box; \
    rm -rf sing-box.tar.gz "sing-box-${SB_VER}-${SB_ARCH}"; \
    sing-box version

# Copy dependencies and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . .

# Ensure data directory exists
RUN mkdir -p /app/data

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
