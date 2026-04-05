"""
stt.py — whisper.cpp STT subprocess wrapper for BrainCache.
Transcribes a WAV audio file to text using whisper.cpp main binary.
Falls back to empty string if whisper is unavailable or fails.
"""

import logging
import os
import re
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def check_whisper_available(config: dict) -> bool:
    whisper_binary = os.path.expandvars(config.get("whisper_binary", ""))
    whisper_model = os.path.expandvars(config.get("whisper_model", ""))
    if not whisper_binary or not Path(whisper_binary).is_file():
        logger.warning("Whisper binary not found: %s", whisper_binary)
        return False
    if not whisper_model or not Path(whisper_model).is_file():
        logger.warning("Whisper model not found: %s", whisper_model)
        return False
    return True


def transcribe_audio(wav_path: str, config: dict) -> str:
    """Transcribe a WAV file to text using whisper.cpp. Returns empty string on failure."""
    if not check_whisper_available(config):
        return ""

    if not Path(wav_path).exists():
        logger.error("WAV file not found: %s", wav_path)
        return ""

    whisper_binary = os.path.expandvars(config.get("whisper_binary", ""))
    whisper_model = os.path.expandvars(config.get("whisper_model", ""))

    cmd = [
        whisper_binary, "-m", whisper_model,
        "-f", wav_path, "-otxt", "--no-timestamps", "-np",
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            logger.error("Whisper failed: %s", result.stderr)
            return ""
    except subprocess.TimeoutExpired:
        logger.warning("Whisper timed out for: %s", wav_path)
        return ""

    txt_path = wav_path + ".txt"
    if not Path(txt_path).exists():
        return ""

    raw = ""
    try:
        with open(txt_path, "r", encoding="utf-8") as f:
            raw = f.read()
    finally:
        try:
            os.unlink(txt_path)
        except OSError:
            pass

    # Clean transcription artifacts
    artifact_patterns = [
        r'\[BLANK_AUDIO\]', r'\(music\)', r'\(applause\)',
        r'\[Music\]', r'\[music\]',
    ]
    lines = raw.split('\n')
    cleaned = []
    for line in lines:
        line = line.strip()
        for pat in artifact_patterns:
            line = re.sub(pat, '', line, flags=re.IGNORECASE)
        line = line.strip()
        if line:
            cleaned.append(line)

    # Remove phrases repeated 3+ times consecutively, keep one
    deduped = []
    i = 0
    while i < len(cleaned):
        phrase = cleaned[i]
        count = 1
        while i + count < len(cleaned) and cleaned[i + count] == phrase:
            count += 1
        deduped.append(phrase)
        i += count

    return '\n'.join(deduped).strip()


def save_webm_as_wav(webm_bytes: bytes, wav_path: str) -> bool:
    """Convert browser MediaRecorder webm/opus output to 16kHz mono WAV via ffmpeg."""
    cmd = [
        "ffmpeg", "-y", "-i", "-",
        "-ar", "16000", "-ac", "1",
        "-f", "wav", wav_path,
    ]
    try:
        result = subprocess.run(cmd, input=webm_bytes, capture_output=True, timeout=30)
        if result.returncode != 0:
            logger.error(
                "ffmpeg failed: %s",
                result.stderr.decode(errors="replace"),
            )
            return False
        return True
    except Exception as exc:
        logger.error("ffmpeg error: %s", exc)
        return False
