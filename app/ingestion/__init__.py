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
        ("Matthias" vs "Matthias Rebel") creates a duplicate node instead
        of extending the existing one. To keep naming consistent, we first
        retrieve what the graph already knows that's relevant to this fact
        and prepend it, so cognify's extractor sees the canonical full name
        and resolves to the same node. Falls back to a plain ingest if
        retrieval returns nothing.
        """
        from app.ingestion import _cognee

        prior = await _cognee.search(fact, user_id, dataset_name)
        if prior:
            # Give the extractor the existing context first, then the new
            # fact — same chunk, so entity names resolve consistently.
            text = f"{prior}\n\n{fact}"
        else:
            text = fact
        return await self.ingest(text, user_id, dataset_name)

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
