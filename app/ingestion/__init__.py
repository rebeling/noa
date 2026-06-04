"""Ingestion part — Cognee storage/retrieval.

Public surface: IngestionService. Internals: _cognee.

Lazy loading: _cognee pulls in cognee (heavy). Its import is deferred to
inside the methods so `import app.ingestion` stays cheap and the server
boots fast.
"""

__all__ = ["IngestionService"]


class IngestionService:
    """Document ingestion and knowledge retrieval over Cognee.

    The heavy cognee dependency loads on first method call, not at import
    or construction time.
    """

    async def ingest(
        self, text: str, user_id: str, dataset_name: str = "default"
    ) -> bool:
        """Write `text` to Cognee for `user_id`."""
        from app.ingestion import _cognee

        return await _cognee.add_document(text, user_id, dataset_name)

    async def ingest_fact(
        self, fact: str, user_id: str, dataset_name: str = "default"
    ) -> bool:
        """Ingest a short spoken fact, merging into existing entities.

        Cognee derives each entity node's id from uuid5(name), so a fact
        that names an entity differently than it's already stored
        ("Matthias" vs "Matthias Rebel") risks a duplicate node. Entity
        resolution is exactly what remember()'s Improve pass does — it
        reconciles new facts against the existing graph. So this is now a
        plain ingest; the merging happens inside cognee.

        (An earlier version retrieved prior context and prepended it to the
        fact to "prime" the extractor. That fed search output back into
        ingestion: cognee's recall returns chunks whose text can already
        contain a stringified search-result dict, which then got re-stored
        as a fact, compounding every turn until the real fact was buried.
        Don't reintroduce that loop.)
        """
        return await self.ingest(fact, user_id, dataset_name)

    async def query(
        self, query: str, user_id: str, dataset_name: str = "default"
    ) -> str:
        """Search a tenant's memory and return only context text."""
        from app.ingestion import _cognee

        return await _cognee.search(query, user_id, dataset_name)

    async def query_with_meta(
        self,
        query: str,
        user_id: str,
        dataset_name: str = "default",
        session_id: str | None = None,
    ):
        """Search a tenant's memory with routing and timing metadata.

        Pass `session_id` to thread cognee conversational sessions (the
        COGNEE_SESSIONS experiment); None keeps the default retrieval path.
        """
        from app.ingestion import _cognee

        return await _cognee.query_with_meta(
            query, user_id, dataset_name, session_id=session_id
        )

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
