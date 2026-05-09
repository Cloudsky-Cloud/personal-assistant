from .vector_store import vector_store


class ContextRetriever:
    async def store_message(self, telegram_id: int, role: str, text: str, msg_id: str):
        vector_store.upsert_memory(
            doc_id=f"msg_{msg_id}",
            text=text,
            metadata={"telegram_id": telegram_id, "role": role, "type": "message"},
        )

    async def store_preference(self, telegram_id: int, preference: str, pref_id: str):
        vector_store.upsert_memory(
            doc_id=f"pref_{pref_id}",
            text=preference,
            metadata={"telegram_id": telegram_id, "type": "preference"},
        )

    async def get_relevant_context(
        self, telegram_id: int, query: str, n: int = 5
    ) -> str:
        results = vector_store.query(text=query, telegram_id=telegram_id, n_results=n)
        if not results:
            return ""
        # Only include results that are reasonably similar (cosine distance < 0.8)
        lines = [f"- {r['text']}" for r in results if r["distance"] < 0.8]
        return "\n".join(lines)


context_retriever = ContextRetriever()
