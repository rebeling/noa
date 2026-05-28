"""Presidio PII/PHI redaction — internal to ingestion."""

from functools import lru_cache

from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_anonymizer import AnonymizerEngine

# Presidio defaults to en_core_web_lg (~560MB) and pip-downloads it on first
# use. We ship the small model as a declared dep instead and point presidio
# at it explicitly — no runtime download, reproducible via uv.lock.
_NLP_CONFIG = {
    "nlp_engine_name": "spacy",
    "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
}


@lru_cache(maxsize=1)
def _get_analyzer() -> AnalyzerEngine:
    nlp_engine = NlpEngineProvider(nlp_configuration=_NLP_CONFIG).create_engine()
    return AnalyzerEngine(nlp_engine=nlp_engine)


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
