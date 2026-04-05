### Stage 1 — Piper TTS builder
FROM debian:bookworm-slim AS piper-builder

RUN apt-get update && apt-get install -y curl tar \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /opt/piper/voices

# Download Piper binary — pick the correct arch (amd64 → x86_64, arm64 → aarch64)
ARG TARGETARCH
RUN PIPER_ARCH=$([ "$TARGETARCH" = "arm64" ] && echo "aarch64" || echo "x86_64") \
    && curl -L \
    https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_${PIPER_ARCH}.tar.gz \
    | tar -xz -C /opt/piper --strip-components=1

# Download voice model and config
RUN curl -L -o /opt/piper/voices/en_US-lessac-medium.onnx \
    https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/lessac/medium/en_US-lessac-medium.onnx

RUN curl -L -o /opt/piper/voices/en_US-lessac-medium.onnx.json \
    https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json

### Stage 2 — whisper.cpp builder
FROM debian:bookworm-slim AS whisper-builder

RUN apt-get update && apt-get install -y \
    git build-essential cmake curl \
    && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/ggerganov/whisper.cpp /opt/whisper-src

WORKDIR /opt/whisper-src

RUN make -j$(nproc)

RUN mkdir -p /opt/whisper/models \
    && cp build/bin/main /opt/whisper/main

RUN bash ./models/download-ggml-model.sh base.en \
    && cp models/ggml-base.en.bin /opt/whisper/models/

### Stage 3 — Python application
FROM python:3.11-slim AS app

RUN apt-get update && apt-get install -y \
    libsndfile1 alsa-utils ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=piper-builder /opt/piper /opt/piper
COPY --from=whisper-builder /opt/whisper /opt/whisper

RUN chmod +x /opt/piper/piper /opt/whisper/main

WORKDIR /app
RUN mkdir -p /app/data

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 7337

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7337"]
