"""
session.py — Feynman session logic for BrainCache.
All AI calls via ollama_client. No API keys.
"""

import logging
from typing import Optional
import ollama_client
import db
import scraper

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a cybersecurity education assistant helping "
    "an analyst learn from threat intelligence articles "
    "using the Feynman learning method. You always respond "
    "with valid JSON only. No text outside the JSON object."
)


def generate_pre_read_prompt(title: str, summary: str) -> dict:
    user_prompt = (
        "Given this threat intelligence article title and "
        "summary, return a JSON object with exactly these "
        "two fields:\n\n"
        '{\n'
        '  "hypothesis_question": "A Socratic question asking '
        "the analyst to predict — based on the title alone "
        "and before reading — what the attacker's initial "
        "access method was and what their likely end goal "
        'was. Start with: Before reading this article...",\n'
        '  "unknown_terms": ["term1", "term2", "term3"]\n'
        '}\n\n'
        "unknown_terms must be 2-5 technical terms or product "
        "names from the title or summary that a non-technical "
        "CTI analyst might not immediately understand.\n\n"
        f"Title: {title}\n"
        f"Summary: {summary}\n\n"
        "Return only the JSON object. No other text."
    )
    result = ollama_client.generate_json(user_prompt, system=_SYSTEM_PROMPT)
    if not isinstance(result, dict):
        raise ValueError(f"Expected dict, got {type(result)}")
    if "hypothesis_question" not in result or "unknown_terms" not in result:
        raise ValueError(f"Missing required keys in model response: {list(result.keys())}")
    return result


def generate_socratic_questions(full_article_text: str) -> list:
    truncated_text = full_article_text[:4000]
    user_prompt = (
        "Read this threat intelligence article excerpt and "
        "return a JSON array of exactly 4 strings. These are "
        "fixed Socratic questions customized to this specific "
        "article. Follow this structure exactly:\n\n"
        "[\n"
        '  "Why did the attacker choose [specific method from '
        "article] as their initial access method, and what "
        'made this target vulnerable to it?",\n\n'
        '  "At what specific point in the timeline could a '
        "defender have detected or stopped this intrusion, "
        "and what detection capability would have been "
        'required?",\n\n'
        '  "What single change — either by the attacker or '
        "the defender — would have produced a completely "
        'different outcome in this incident?",\n\n'
        '  "You have 90 seconds to brief an MSSP client '
        "executive on this incident. What are the three "
        'most important points they need to understand?"\n'
        "]\n\n"
        "Customize each question to reference specific details "
        "from this article — tools used, techniques, timeline, "
        "actor behavior. Do not use generic placeholders.\n\n"
        f"Article excerpt:\n{truncated_text}\n\n"
        "Return only the JSON array. No other text."
    )
    result = ollama_client.generate_json(user_prompt, system=_SYSTEM_PROMPT)
    if not isinstance(result, list):
        raise ValueError(f"Expected list, got {type(result)}")
    if len(result) != 4:
        raise ValueError(f"Expected exactly 4 questions, got {len(result)}")
    return result


def generate_session_summary(article_url: str, session_logs: list) -> dict:
    formatted_responses = "\n\n".join(
        "Phase: {}\nPrompt: {}\nResponse: {}".format(
            log.get("phase", "unknown"),
            log.get("prompt_text", ""),
            log.get("user_response", ""),
        )
        for log in session_logs
    )
    user_prompt = (
        "A cybersecurity analyst just completed a Feynman "
        "learning session on a threat intelligence article. "
        "Here are their responses to each prompt:\n\n"
        f"{formatted_responses}\n\n"
        "Analyze their responses and return a JSON object:\n"
        "{\n"
        '  "strong_points": ["thing they explained well 1",\n'
        '                     "thing they explained well 2"],\n'
        '  "gap_terms": ["term or concept they struggled '
        'with 1", "gap 2"],\n'
        '  "recommended_entries": ["term to add to notebook 1",\n'
        '                          "term 2"]\n'
        "}\n\n"
        "strong_points: concepts they clearly understood.\n"
        "gap_terms: concepts they avoided, got wrong, or "
        "used jargon to avoid explaining.\n"
        "recommended_entries: specific technical terms from "
        "the session that should be added to their "
        "I Don't Know notebook for further study.\n\n"
        "Return only the JSON object. No other text."
    )
    result = ollama_client.generate_json(user_prompt, system=_SYSTEM_PROMPT)
    if not isinstance(result, dict):
        raise ValueError(f"Expected dict, got {type(result)}")
    return result
