"""
ChromaMemoryService — ADK-compatible vector memory backend for Mail Bot.

Implements BaseMemoryService for ADK integration, plus a set of callable
tool functions to be passed directly to the Memory Agent.

Dependencies:
    pip install chromadb google-adk
"""

import uuid
import logging
from datetime import datetime, timezone
from typing import Optional

import chromadb
from chromadb.utils import embedding_functions

from google.adk.memory import BaseMemoryService
from google.adk.memory.base_memory_service import SearchMemoryResponse
from google.adk.memory.memory_entry import MemoryEntry
from google.adk.sessions import Session
from google.adk.tools import ToolContext
from google.genai.types import Content, Part

logger = logging.getLogger(__name__)

MEMORY_TYPES = ("personal_fact", "task_context", "preference")


def _where(**clauses) -> dict:
    """Build a Chroma where clause; wraps multi-key filters in $and."""
    items = [{k: v} for k, v in clauses.items() if v is not None]
    if not items:
        return {}
    if len(items) == 1:
        return items[0]
    return {"$and": items}


class ChromaMemoryService(BaseMemoryService):
    """
    Persistent vector memory backed by ChromaDB.

    ADK calls:
        search_memory()          — auto-injects relevant memories at session start
        add_session_to_memory()  — called by /closesession to flush a session

    Agent tools (pass these to your Memory Agent's tools= list):
        save_memory()
        recall_memory()
        forget_memory()
        list_memories()
    """

    def __init__(self, path: str = "./memory_db"):
        self.client = chromadb.PersistentClient(path=path)
        self.ef = embedding_functions.DefaultEmbeddingFunction()
        self.collection = self.client.get_or_create_collection(
            name="mailbot_memories",
            embedding_function=self.ef,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(f"ChromaMemoryService initialised at {path!r}")

    # ------------------------------------------------------------------
    # ADK BaseMemoryService interface
    # ------------------------------------------------------------------

    async def add_session_to_memory(self, session: Session) -> None:
        chunks = self._chunk_session(session)
        if not chunks:
            logger.info(f"Session {session.id} had no embeddable content.")
            return

        for i, chunk in enumerate(chunks):
            doc_id = f"{session.id}-{i}"
            self.collection.upsert(
                ids=[doc_id],
                documents=[chunk["text"]],
                metadatas=[{
                    "user_id": session.user_id,
                    "app_name": session.app_name,
                    "session_id": session.id,
                    "memory_type": chunk.get("memory_type", "task_context"),
                    "timestamp": chunk["timestamp"],
                    "source": "session_close",
                }],
            )
        logger.info(f"Committed {len(chunks)} chunks from session {session.id}")

    async def search_memory(
        self,
        *,
        app_name: str,
        user_id: str,
        query: str,
    ) -> SearchMemoryResponse:
        results = self.collection.query(
            query_texts=[query],
            n_results=5,
            where={"user_id": user_id},
        )

        response = SearchMemoryResponse()
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        ids = results.get("ids", [[]])[0]

        for doc, meta, doc_id in zip(docs, metas, ids):
            timestamp = meta.get("timestamp")
            response.memories.append(
                MemoryEntry(
                    id=doc_id,
                    content=Content(parts=[Part(text=doc)]),
                    timestamp=timestamp,
                    custom_metadata=dict(meta),
                )
            )

        return response

    # ------------------------------------------------------------------
    # Agent-facing tool functions
    # ------------------------------------------------------------------

    def save_memory(
        self,
        fact: str,
        memory_type: str,
        tool_context: ToolContext,
    ) -> str:
        """
        Save a single memory fact to the vector store.

        Args:
            fact: A single declarative sentence describing the fact to remember.
                  E.g. "Owen prefers bullet point email summaries."
            memory_type: One of 'personal_fact', 'task_context', or 'preference'.
        """
        if memory_type not in MEMORY_TYPES:
            return (
                f"Invalid memory_type '{memory_type}'. "
                f"Must be one of: {', '.join(MEMORY_TYPES)}"
            )

        user_id = tool_context.user_id
        doc_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        self.collection.upsert(
            ids=[doc_id],
            documents=[fact],
            metadatas=[{
                "user_id": user_id,
                "memory_type": memory_type,
                "timestamp": timestamp,
                "source": "explicit_save",
                "doc_id": doc_id,
            }],
        )

        logger.info(f"Saved [{memory_type}] for {user_id}: {fact!r}")
        return f"Saved {memory_type}: {fact}"

    def recall_memory(
        self,
        query: str,
        memory_type: Optional[str],
        tool_context: ToolContext,
    ) -> str:
        """
        Search memory for facts relevant to a query.

        Args:
            query: Natural language description of what to recall.
            memory_type: Optional filter. One of 'personal_fact',
                         'task_context', 'preference', or None for all types.
        """
        user_id = tool_context.user_id
        type_filter = memory_type if memory_type in MEMORY_TYPES else None

        results = self.collection.query(
            query_texts=[query],
            n_results=8,
            where=_where(user_id=user_id, memory_type=type_filter),
        )

        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]

        if not docs:
            return "No relevant memories found."

        lines = []
        for doc, meta in zip(docs, metas):
            ts = meta.get("timestamp", "?")
            mt = meta.get("memory_type", "memory")
            lines.append(f"[{mt} | {ts}] {doc}")

        return "\n".join(lines)

    def forget_memory(
        self,
        query: str,
        confirmed: bool,
        tool_context: ToolContext,
    ) -> str:
        """
        Delete memories matching a query. Requires explicit confirmation.

        Args:
            query: Description of what to forget.
            confirmed: Must be True to actually delete. If False, returns a
                       preview of what would be deleted.
        """
        user_id = tool_context.user_id

        results = self.collection.query(
            query_texts=[query],
            n_results=5,
            where={"user_id": user_id},
        )

        for doc, dist in zip(results["documents"][0], results["distances"][0]):
            logger.info(f"{dist:.4f}  {doc}")

        docs = results.get("documents", [[]])[0]
        ids = results.get("ids", [[]])[0]
        metas = results.get("metadatas", [[]])[0]

        if not ids:
            return "No matching memories found."

        preview_lines = []
        for doc, meta in zip(docs, metas):
            ts = meta.get("timestamp", "?")
            preview_lines.append(f"- [{ts}] {doc}")
        preview = "\n".join(preview_lines)

        if not confirmed:
            return (
                f"Found {len(ids)} memory/memories to delete:\n{preview}\n\n"
                "Call forget_memory again with confirmed=True to delete."
            )

        self.collection.delete(ids=ids)
        logger.info(f"Deleted {len(ids)} memories for {user_id}: {ids}")
        return f"Deleted {len(ids)} memory/memories:\n{preview}"

    def list_memories(
        self,
        memory_type: Optional[str],
        limit: int,
        tool_context: ToolContext,
    ) -> str:
        """
        List stored memories, optionally filtered by type.

        Args:
            memory_type: Optional filter. One of 'personal_fact',
                         'task_context', 'preference', or None for all.
            limit: Maximum number of memories to return (max 50).
        """
        user_id = tool_context.user_id
        limit = min(max(1, limit), 50)
        type_filter = memory_type if memory_type in MEMORY_TYPES else None

        results = self.collection.get(
            where=_where(user_id=user_id, memory_type=type_filter),
            limit=limit,
        )

        docs = results.get("documents") or []
        metas = results.get("metadatas") or []

        if not docs:
            filter_str = f" of type '{memory_type}'" if memory_type else ""
            return f"No memories found{filter_str}."

        lines = []
        for doc, meta in zip(docs, metas):
            ts = meta.get("timestamp", "?")
            mt = meta.get("memory_type", "memory")
            doc_id = (meta.get("doc_id") or "?")[:8]
            lines.append(f"[{mt} | {ts} | id:{doc_id}] {doc}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _chunk_session(self, session: Session) -> list[dict]:
        """Extract substantive user/model turns from a session's events."""
        chunks = []
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        for event in session.events:
            if not event.content or not event.content.parts:
                continue

            role = getattr(event.content, "role", None) or getattr(event, "author", None)
            if role not in ("user", "model"):
                continue

            text_parts = [
                p.text for p in event.content.parts
                if getattr(p, "text", None) and p.text.strip()
            ]
            text = " ".join(text_parts).strip()

            if len(text) < 40:
                continue

            chunks.append({
                "text": text,
                "timestamp": timestamp,
                "memory_type": "task_context",
            })

        return chunks
