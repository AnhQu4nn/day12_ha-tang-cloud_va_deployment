from __future__ import annotations

from pathlib import Path
from typing import Any


class ChromaPolicyStore:
    """Student scaffold for the real Chroma-backed policy index."""

    def __init__(
        self,
        persist_directory: Path,
        embedding_model: Any,
        collection_name: str = "policy_chunks",
    ) -> None:
        import chromadb
        self.client = chromadb.PersistentClient(path=str(persist_directory))
        self.collection = self.client.get_or_create_collection(name=collection_name)
        self.embedding_model = embedding_model

    def ensure_index(self, markdown_path: Path) -> None:
        if self.collection.count() == 0:
            self.rebuild(markdown_path)

    def rebuild(self, markdown_path: Path) -> None:
        from .parser import parse_policy_markdown
        
        with open(markdown_path, "r", encoding="utf-8") as f:
            markdown_text = f.read()
            
        chunks = parse_policy_markdown(markdown_text)
        if not chunks:
            return
            
        documents = [c["rendered_text"] for c in chunks]
        metadatas = [
            {"section_h2": c["section_h2"], "section_h3": c["section_h3"], "citation": c["citation"]}
            for c in chunks
        ]
        ids = [f"chunk_{i}" for i in range(len(chunks))]
        
        embeddings = self.embedding_model.embed_documents(documents)
        
        self.collection.add(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=embeddings
        )

    def search(self, query: str, top_k: int = 4) -> list[dict[str, Any]]:
        query_embedding = self.embedding_model.embed_query(query)
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k
        )
        
        hits = []
        if results and results["documents"] and results["documents"][0]:
            for i in range(len(results["documents"][0])):
                hits.append({
                    "content": results["documents"][0][i],
                    "citation": results["metadatas"][0][i].get("citation", ""),
                    "distance": results["distances"][0][i] if results.get("distances") else 0.0
                })
        return hits
