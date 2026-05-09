from pathlib import Path
from ..config import settings


class VectorStore:
    def __init__(self):
        self._client = None
        self._collection = None

    def init(self):
        import chromadb
        from chromadb.utils import embedding_functions

        Path(settings.chroma_path).mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=settings.chroma_path)
        ef = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2"
        )
        self._collection = self._client.get_or_create_collection(
            name="assistant_memory",
            embedding_function=ef,
            metadata={"hnsw:space": "cosine"},
        )

    def upsert_memory(self, doc_id: str, text: str, metadata: dict):
        if self._collection is None:
            return
        clean_meta = {k: v for k, v in metadata.items() if v is not None}
        self._collection.upsert(ids=[doc_id], documents=[text], metadatas=[clean_meta])

    def query(
        self,
        text: str,
        telegram_id: int,
        n_results: int = 5,
        where: dict | None = None,
    ) -> list[dict]:
        if self._collection is None:
            return []
        filter_clause: dict = {"telegram_id": telegram_id}
        if where:
            filter_clause.update(where)
        try:
            results = self._collection.query(
                query_texts=[text],
                n_results=n_results,
                where=filter_clause,
            )
        except Exception:
            return []
        output = []
        for i, doc in enumerate(results["documents"][0]):
            output.append(
                {
                    "text": doc,
                    "metadata": results["metadatas"][0][i],
                    "distance": results["distances"][0][i],
                }
            )
        return output

    def delete_by_user(self, telegram_id: int):
        if self._collection is None:
            return
        self._collection.delete(where={"telegram_id": telegram_id})


vector_store = VectorStore()
