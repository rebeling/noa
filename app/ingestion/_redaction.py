"""Presidio PII/PHI redaction — internal to ingestion."""

from functools import lru_cache

from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine


@lru_cache(maxsize=1)
def _get_analyzer() -> AnalyzerEngine:
    return AnalyzerEngine()


@lru_cache(maxsize=1)
def _get_anonymizer() -> AnonymizerEngine:
    return AnonymizerEngine()


def redact_text(text: str) -> str:
    """Replace detected PII/PHI entities in `text` with placeholders."""
    results = _get_analyzer().analyze(text=text, entities=[], language="en")
    anonymized = _get_anonymizer().anonymize(
        text=text, analyzer_results=results
    )
    return anonymized.text
