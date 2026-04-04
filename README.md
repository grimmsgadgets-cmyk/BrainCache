# BrainCache

Local Linux CTI learning tool — Socratic sessions, voice
interaction, and an I Don't Know notebook. Powered entirely
by local AI via Ollama. No API keys. No accounts. No cloud.

> **Status: in development.**
> Session 1 complete — Docker infrastructure and Ollama client
> are in place. Application logic is not yet built. The stack
> will not run until a later session adds `main.py` and the
> remaining backend modules.

## Quick start

    git clone https://github.com/grimmsgadgets-cmyk/BrainCache
    cd BrainCache
    cp .env.example .env
    docker compose up --build

Open http://localhost:7337

That is the complete setup. Nothing else required.

On first run, Ollama automatically pulls the default model
(llama3.2, approximately 2GB). This happens once and is
cached in a Docker volume. All subsequent starts are instant.

## Requirements

- Docker and Docker Compose installed
- Linux desktop with audio hardware (for voice features)
- 8GB RAM minimum, 16GB recommended
- ~5GB disk space (model + app + dependencies)

## Changing the AI model

Edit .env before starting:

    OLLAMA_MODEL=mistral

Any model from https://ollama.com/library works.
Recommended for this use case:
- llama3.2 (default — good quality, moderate size)
- mistral (fast, smaller)
- phi3 (very fast, smaller, good for weaker hardware)
- llama3.1 (higher quality, larger)

## Audio (voice features)

Piper TTS and whisper.cpp are built into the Docker image.
docker-compose.yml mounts /dev/snd automatically.

If you get no audio output:

    sudo usermod -aG audio $USER

Log out and back in after running this.

## GPU acceleration (optional)

If your machine has an NVIDIA GPU, Ollama will use it
automatically if the NVIDIA Container Toolkit is installed.
See: https://ollama.com/blog/nvidia-gpu

## Architecture

BrainCache runs two Docker services:

- ollama: local LLM inference, no internet required after
  initial model pull
- braincache: FastAPI backend + vanilla JS frontend,
  Piper TTS, whisper.cpp STT, SQLite database

No data leaves your machine.
