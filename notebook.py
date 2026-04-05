"""
notebook.py — I Don't Know notebook logic for BrainCache.
Feynman-structured entries generated via local Ollama.
No API keys.
"""

import logging
import time
from typing import Optional
import ollama_client
import db

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a cybersecurity education assistant using "
    "the Feynman learning method. You always respond with "
    "valid JSON only. No text outside the JSON object."
)


def generate_notebook_entry(
    db_path: str,
    term: str,
    source_article_url: Optional[str] = None,
) -> dict:
    existing = db.get_notebook_entry_by_term(db_path, term)
    if existing:
        logger.info(
            "Duplicate notebook entry detected for term: %s — returning existing", term
        )
        return existing

    user_prompt = (
        f"Generate a Feynman learning notebook entry for this "
        f"cybersecurity term or concept: '{term}'\n\n"
        "Return a JSON object with exactly these fields:\n\n"
        "{\n"
        '  "hypothesis_prompt": "A question asking the learner '
        "to guess what this term means before being told. "
        'Start with: Before I explain — what do you think...",\n\n'
        '  "plain_explanation": "What this term means in 1-2 '
        "sentences using zero technical jargon. Explain it "
        'as if the reader has never worked in IT. Use an analogy if helpful.",\n\n'
        '  "mitre_reference": "The MITRE ATT&CK technique ID '
        "and full name if this term maps to a specific "
        "technique (e.g. T1190 - Exploit Public-Facing "
        'Application). Return null if not applicable.",\n\n'
        '  "socratic_questions": [\n'
        '    "A question about why an attacker would use this",\n'
        '    "A question about what this leaves behind or '
        'how a defender would detect it",\n'
        '    "A question about what prerequisite access or '
        'condition this technique requires"\n'
        "  ],\n\n"
        '  "resolution_target": "The exact one-sentence '
        "plain-language explanation the learner must be able "
        "to say clearly and without looking, to consider "
        'this entry resolved. No jargon allowed."\n'
        "}\n\n"
        "Return only the JSON object. No other text."
    )

    MAX_RETRIES = 2
    last_error = None
    result = None
    for attempt in range(MAX_RETRIES):
        try:
            result = ollama_client.generate_json(user_prompt, system=_SYSTEM_PROMPT, timeout=90)
            if not isinstance(result, dict):
                raise ValueError(f"Expected dict from model, got {type(result)}")
            break
        except ValueError as exc:
            last_error = exc
            logger.warning("Attempt %d/%d: JSON parse failed — %s", attempt + 1, MAX_RETRIES, exc)
            if attempt < MAX_RETRIES - 1:
                time.sleep(3)
        except Exception as exc:
            last_error = exc
            logger.warning("Attempt %d/%d: Ollama call failed — %s", attempt + 1, MAX_RETRIES, exc)
            if attempt < MAX_RETRIES - 1:
                time.sleep(3)
    if result is None:
        raise ValueError(f"Failed after {MAX_RETRIES} attempts: {last_error}")
    if not isinstance(result, dict):
        raise ValueError(f"Expected dict from model, got {type(result)}")

    try:
        entry = db.insert_notebook_entry(
            db_path,
            term=term,
            hypothesis_prompt=result.get("hypothesis_prompt"),
            plain_explanation=result.get("plain_explanation"),
            mitre_reference=result.get("mitre_reference"),
            socratic_questions=result.get("socratic_questions", []),
            resolution_target=result.get("resolution_target"),
            source_article_url=source_article_url,
        )
        return entry
    except Exception as exc:
        logger.error(
            "Failed to save notebook entry for term '%s': %s", term, exc
        )
        raise
