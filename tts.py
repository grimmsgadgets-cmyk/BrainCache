"""
tts.py — Piper TTS subprocess wrapper for BrainCache.
Calls the Piper binary to synthesize speech from text
and plays it via aplay (Linux ALSA).
Falls back silently if Piper is unavailable.
"""

import asyncio
import logging
import os
import re
import shlex
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


def check_piper_available(config: dict) -> bool:
    piper_binary = os.path.expandvars(config.get("piper_binary", ""))
    piper_model = os.path.expandvars(config.get("piper_model", ""))
    if not piper_binary or not Path(piper_binary).is_file():
        logger.warning("Piper binary not found: %s", piper_binary)
        return False
    if not piper_model or not Path(piper_model).is_file():
        logger.warning("Piper model not found: %s", piper_model)
        return False
    return True


def speak(text: str, config: dict) -> bool:
    """Blocking TTS synthesis and playback. Returns True on success."""
    if not check_piper_available(config):
        return False

    piper_binary = os.path.expandvars(config.get("piper_binary", ""))
    piper_model = os.path.expandvars(config.get("piper_model", ""))

    # Clean text before sending to Piper
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\s+', ' ', text)
    text = text.strip()
    text = text[:2000]

    tmp_file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp_wav_path = tmp_file.name
    tmp_file.close()

    try:
        cmd = (
            f'echo {shlex.quote(text)} | '
            f'{shlex.quote(piper_binary)} --model {shlex.quote(piper_model)} '
            f'--output_file {shlex.quote(tmp_wav_path)}'
        )
        result = subprocess.run(cmd, shell=True, capture_output=True, timeout=30)
        if result.returncode != 0:
            logger.error(
                "Piper failed (rc=%d): %s",
                result.returncode,
                result.stderr.decode(errors="replace"),
            )
            return False

        try:
            subprocess.run(["aplay", "-q", tmp_wav_path], capture_output=True, timeout=30)
        except Exception as exc:
            logger.warning("aplay playback failed (non-fatal): %s", exc)

        return True

    except subprocess.CalledProcessError as exc:
        logger.error("Piper CalledProcessError: %s", exc)
        return False
    except subprocess.TimeoutExpired as exc:
        logger.error("Piper timed out: %s", exc)
        return False
    except Exception as exc:
        logger.error("Piper unexpected error: %s", exc)
        return False
    finally:
        try:
            os.unlink(tmp_wav_path)
        except OSError:
            pass


async def speak_async(text: str, config: dict) -> None:
    """Non-blocking TTS. Runs speak() in a thread pool executor."""
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, speak, text, config)
    except Exception as exc:
        logger.error("speak_async error: %s", exc)


def speak_prompt(text: str, config: dict) -> None:
    """Speak a session prompt aloud. Silently continues on TTS failure."""
    result = speak(text, config)
    if not result:
        logger.info("TTS unavailable, continuing in text-only mode")
