"""Ingestion part — document redaction + Cognee storage/retrieval.

Public surface: IngestionService. Internals: _redaction, _cognee.

Invariant: ingest() redacts before any document reaches Cognee. There
is no code path to Cognee that skips redaction.

Lazy loading: _redaction pulls in presidio and _cognee pulls in cognee,
both heavy. Their imports are deferred to inside the methods so
`import app.ingestion` stays cheap and the server boots fast.
"""

__all__ = ["IngestionService"]


class IngestionService:
    """Document ingestion and knowledge retrieval over Cognee.

    Heavy dependencies (presidio, cognee) load on first method call,
    not at import or construction time.
    """

    async def ingest(
        self, text: str, user_id: str, dataset_name: str = "default"
    ) -> bool:
        """Redact `text`, then write it to Cognee for `user_id`.

        Redaction is mandatory here unless settings.REDACTION_ENABLED is
        explicitly false (dev-only). There is no other path to Cognee that
        skips it.
        """
        from app.core.config import settings
        from app.ingestion import _cognee

        if settings.REDACTION_ENABLED:
            from app.ingestion._redaction import redact_text

            text = redact_text(text)
        return await _cognee.add_document(text, user_id, dataset_name)

    async def query(
        self, query: str, user_id: str, dataset_name: str = "default"
    ) -> str:
        """Search a tenant's knowledge graph."""
        from app.ingestion import _cognee

        return await _cognee.search(query, user_id, dataset_name)

    async def visualize(
        self, user_id: str, dataset_name: str = "default"
    ) -> str:
        """Render a tenant's knowledge graph as a standalone HTML page."""
        from app.ingestion import _cognee

        return await _cognee.visualize(user_id, dataset_name)

    async def reset(self) -> None:
        """Wipe all Cognee data (every tenant). Dev reset only."""
        from app.ingestion import _cognee

        await _cognee.reset()
