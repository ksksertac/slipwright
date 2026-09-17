"""Retrieval over the standards corpus (RAG), stored in SQLite.

Chunks live in ``standards.sqlite3`` with an FTS5 index for keyword (BM25) search and,
when an embedder is configured, an embedding per chunk for semantic search; ``search``
merges both. Indexing is incremental by chunk id (a content hash), so unchanged sections
are never re-embedded. Chroma, pgvector or Qdrant can replace this class behind the
same ``search`` / ``reindex`` surface if a corpus ever outgrows SQLite.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import struct
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx

from slipwright.standards import Chunk, Page, chunk_corpus

_TOKEN = re.compile(r"[\w][\w'-]{1,}", re.UNICODE)


# -- embedders ---------------------------------------------------------------------------------


class Embedder(Protocol):
    name: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class NoEmbedder:
    """Keyword search only."""

    name = "none"

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[] for _ in texts]


class HashingEmbedder:
    """Deterministic bag-of-words hashing into ``dim`` buckets. No model, no network:
    used by tests and as a stand-in when nothing else is configured but embeddings are
    wanted. It captures word overlap, not meaning."""

    name = "hashing"

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for text in texts:
            vec = [0.0] * self.dim
            for tok in _TOKEN.findall(text.lower()):
                h = int(hashlib.blake2b(tok.encode(), digest_size=4).hexdigest(), 16)
                vec[h % self.dim] += 1.0
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            out.append([v / norm for v in vec])
        return out


class OpenAIEmbedder:
    """OpenAI (or compatible) ``/embeddings``; the model id comes from settings."""

    name = "openai"

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.model = model
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}", "User-Agent": "slipwright"},
            transport=transport,
            timeout=60.0,
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        out: list[list[float]] = []
        for start in range(0, len(texts), 64):
            batch = texts[start : start + 64]
            resp = self._client.post("/embeddings", json={"model": self.model, "input": batch})
            if resp.status_code >= 400:
                raise StandardsIndexError(
                    f"embeddings API error {resp.status_code}: {resp.text[:200]}"
                )
            data = sorted(resp.json()["data"], key=lambda d: d["index"])
            out.extend([list(map(float, d["embedding"])) for d in data])
        return out


class LocalEmbedder:
    """sentence-transformers model on this machine (``uv sync --extra local-embeddings``)."""

    name = "local"

    def __init__(self, model_name: str) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - optional extra
            raise StandardsIndexError(
                "local embeddings need the optional extra: uv sync --extra local-embeddings"
            ) from exc
        self.model = SentenceTransformer(model_name)

    def embed(self, texts: list[str]) -> list[list[float]]:  # pragma: no cover - optional
        if not texts:
            return []
        vectors = self.model.encode(texts, normalize_embeddings=True)
        return [list(map(float, v)) for v in vectors]


class StandardsIndexError(RuntimeError):
    pass


# -- the index -------------------------------------------------------------------------------


@dataclass(frozen=True)
class Hit:
    chunk: Chunk
    score: float
    keyword: float
    semantic: float

    def as_context(self) -> dict[str, Any]:
        return {
            "id": self.chunk.id,
            "domain": self.chunk.domain,
            "page": self.chunk.page,
            "heading": f"{self.chunk.title} — {self.chunk.heading}",
            "text": self.chunk.text,
            "scope": self.chunk.scope,
            "score": round(self.score, 3),
        }


_SCHEMA = """
CREATE TABLE IF NOT EXISTS chunks (
    id         TEXT PRIMARY KEY,
    scope      TEXT NOT NULL,
    project_id TEXT,
    domain     TEXT NOT NULL,
    page       TEXT NOT NULL,
    title      TEXT NOT NULL,
    heading    TEXT NOT NULL,
    text       TEXT NOT NULL,
    tags       TEXT NOT NULL,
    embedder   TEXT NOT NULL,
    embedding  BLOB
);
CREATE INDEX IF NOT EXISTS chunks_domain ON chunks(domain, scope, project_id);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    id UNINDEXED, heading, text, tags, tokenize = 'porter unicode61'
);
CREATE TABLE IF NOT EXISTS fingerprints (
    scope_key TEXT PRIMARY KEY,
    value     TEXT NOT NULL
);
"""


def _pack(vec: list[float]) -> bytes:
    return struct.pack(f"<{len(vec)}f", *vec)


def _unpack(blob: bytes) -> list[float]:
    n = len(blob) // 4
    return list(struct.unpack(f"<{n}f", blob))


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def _match_query(query: str) -> str:
    """A safe FTS5 MATCH expression: quoted tokens joined with OR."""
    tokens = [t.lower() for t in _TOKEN.findall(query)][:32]
    return " OR ".join(f'"{t}"' for t in tokens)


def corpus_fingerprint(paths: list[Path]) -> str:
    """Cheap change detector over the files of a corpus (names, sizes, mtimes)."""
    parts = []
    for path in sorted(paths):
        st = path.stat()
        parts.append(f"{path.as_posix()}:{st.st_size}:{st.st_mtime_ns}")
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


class StandardsIndex:
    def __init__(self, path: Path | str, embedder: Embedder | None = None) -> None:
        self.path = Path(path)
        self.embedder: Embedder = embedder or NoEmbedder()
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- indexing ------------------------------------------------------------------------

    def reindex(self, pages: list[Page], *, project_id: str | None = None) -> dict[str, int]:
        """Index ``pages`` for one scope (global when ``project_id`` is None): insert new
        chunks (embedding only those), drop chunks that no longer exist, keep the rest."""
        wanted = {c.id: c for c in chunk_corpus(pages)}
        scope_sql, scope_args = self._scope_clause(project_id)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT id, embedder FROM chunks WHERE {scope_sql}", scope_args
            ).fetchall()
            existing = {r["id"]: r["embedder"] for r in rows}
            stale = [cid for cid in existing if cid not in wanted]
            # re-embed chunks indexed with a different embedder
            new_ids = [
                cid for cid in wanted if cid not in existing or existing[cid] != self.embedder.name
            ]
            new_chunks = [wanted[cid] for cid in new_ids]
            vectors = self.embedder.embed([c.document for c in new_chunks])
            self._conn.execute("BEGIN")
            try:
                for cid in stale + [c.id for c in new_chunks if c.id in existing]:
                    self._conn.execute("DELETE FROM chunks WHERE id = ?", (cid,))
                    self._conn.execute("DELETE FROM chunks_fts WHERE id = ?", (cid,))
                for chunk, vec in zip(new_chunks, vectors, strict=True):
                    self._conn.execute(
                        "INSERT INTO chunks (id, scope, project_id, domain, page, title, heading, "
                        "text, tags, embedder, embedding) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            chunk.id,
                            chunk.scope,
                            project_id,
                            chunk.domain,
                            chunk.page,
                            chunk.title,
                            chunk.heading,
                            chunk.text,
                            " ".join(chunk.tags),
                            self.embedder.name,
                            _pack(vec) if vec else None,
                        ),
                    )
                    self._conn.execute(
                        "INSERT INTO chunks_fts (id, heading, text, tags) VALUES (?, ?, ?, ?)",
                        (
                            chunk.id,
                            f"{chunk.title} {chunk.heading}",
                            chunk.text,
                            " ".join(chunk.tags),
                        ),
                    )
                self._conn.execute("COMMIT")
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
        return {"added": len(new_chunks), "removed": len(stale), "total": len(wanted)}

    def fingerprint(self, project_id: str | None) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM fingerprints WHERE scope_key = ?", (project_id or "",)
            ).fetchone()
        return None if row is None else str(row["value"])

    def set_fingerprint(self, project_id: str | None, value: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO fingerprints (scope_key, value) VALUES (?, ?) "
                "ON CONFLICT(scope_key) DO UPDATE SET value = excluded.value",
                (project_id or "", value),
            )

    def stats(self) -> dict[str, Any]:
        with self._lock:
            total = self._conn.execute("SELECT COUNT(*) AS n FROM chunks").fetchone()["n"]
            per_domain = {
                r["domain"]: r["n"]
                for r in self._conn.execute(
                    "SELECT domain, COUNT(*) AS n FROM chunks GROUP BY domain ORDER BY domain"
                )
            }
            embedded = self._conn.execute(
                "SELECT COUNT(*) AS n FROM chunks WHERE embedding IS NOT NULL"
            ).fetchone()["n"]
        return {
            "chunks": int(total),
            "embedded": int(embedded),
            "embedder": self.embedder.name,
            "per_domain": per_domain,
        }

    # -- search --------------------------------------------------------------------------

    def search(
        self, query: str, domain: str | None = None, *, k: int = 4, project_id: str | None = None
    ) -> list[Hit]:
        """Hybrid ranking: BM25 over FTS5 merged with cosine over embeddings (when the
        query and the chunks are embedded). Project chunks win ties over global ones."""
        if not query.strip():
            return []
        scope_sql = "(scope = 'global' OR project_id = ?)"
        args: list[Any] = [project_id or ""]
        if domain and domain != "*":
            scope_sql += " AND domain = ?"
            args.append(domain)
        with self._lock:
            rows = self._conn.execute(f"SELECT * FROM chunks WHERE {scope_sql}", args).fetchall()
            if not rows:
                return []
            keyword: dict[str, float] = {}
            match = _match_query(query)
            if match:
                for r in self._conn.execute(
                    # column weights: a heading hit is worth more than a body hit, tags least
                    "SELECT id, bm25(chunks_fts, 4.0, 1.0, 0.3) AS rank FROM chunks_fts "
                    "WHERE chunks_fts MATCH ?",
                    (match,),
                ):
                    keyword[r["id"]] = -float(r["rank"])  # bm25() is negative: lower is better
        semantic: dict[str, float] = {}
        if not isinstance(self.embedder, NoEmbedder):
            (qvec,) = self.embedder.embed([query])
            for r in rows:
                if r["embedding"] is not None:
                    semantic[r["id"]] = _cosine(qvec, _unpack(r["embedding"]))
        kw_n = _normalise(keyword)
        sem_n = _normalise(semantic)
        # reciprocal rank fusion: robust to the two signals living on different scales
        fused = _rrf(keyword, semantic)
        hits: list[Hit] = []
        for r in rows:
            kw, sem = kw_n.get(r["id"], 0.0), sem_n.get(r["id"], 0.0)
            if r["id"] not in keyword and r["id"] not in semantic:
                continue
            score = fused[r["id"]]
            if r["scope"] == "project":
                score += 0.05
            hits.append(
                Hit(
                    chunk=Chunk(
                        id=r["id"],
                        scope=r["scope"],
                        domain=r["domain"],
                        page=r["page"],
                        title=r["title"],
                        heading=r["heading"],
                        text=r["text"],
                        tags=tuple(r["tags"].split()) if r["tags"] else (),
                    ),
                    score=score,
                    keyword=kw,
                    semantic=sem,
                )
            )
        hits.sort(key=lambda h: (-h.score, h.chunk.page, h.chunk.heading))
        return hits[:k]

    def browse(
        self, domain: str | None = None, *, k: int = 4, project_id: str | None = None
    ) -> list[Hit]:
        """The first ``k`` sections of a domain in page order, project pages first: what
        a role reads when nothing in its domain matches the query."""
        scope_sql = "(scope = 'global' OR project_id = ?)"
        args: list[Any] = [project_id or ""]
        if domain and domain != "*":
            scope_sql += " AND domain = ?"
            args.append(domain)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM chunks WHERE {scope_sql} "
                "ORDER BY CASE scope WHEN 'project' THEN 0 ELSE 1 END, page, rowid LIMIT ?",
                [*args, k],
            ).fetchall()
        return [Hit(chunk=self._chunk(r), score=0.0, keyword=0.0, semantic=0.0) for r in rows]

    # -- helpers -------------------------------------------------------------------------

    @staticmethod
    def _chunk(r: sqlite3.Row) -> Chunk:
        return Chunk(
            id=r["id"],
            scope=r["scope"],
            domain=r["domain"],
            page=r["page"],
            title=r["title"],
            heading=r["heading"],
            text=r["text"],
            tags=tuple(r["tags"].split()) if r["tags"] else (),
        )

    @staticmethod
    def _scope_clause(project_id: str | None) -> tuple[str, tuple[Any, ...]]:
        if project_id is None:
            return "scope = 'global'", ()
        return "scope = 'project' AND project_id = ?", (project_id,)


def _rrf(*rankings: dict[str, float], k: int = 60) -> dict[str, float]:
    """Reciprocal rank fusion of score maps (higher score = better), scaled to [0, 1]."""
    fused: dict[str, float] = {}
    for ranking in rankings:
        if not ranking:
            continue
        ordered = sorted(ranking, key=lambda cid: -ranking[cid])
        for rank, cid in enumerate(ordered, start=1):
            fused[cid] = fused.get(cid, 0.0) + 1.0 / (k + rank)
    if not fused:
        return {}
    best = max(fused.values())
    return {cid: v / best for cid, v in fused.items()}


def _normalise(scores: dict[str, float]) -> dict[str, float]:
    if not scores:
        return {}
    lo, hi = min(scores.values()), max(scores.values())
    if hi - lo < 1e-9:
        return {k: 1.0 for k in scores}
    return {k: (v - lo) / (hi - lo) for k, v in scores.items()}


def dumps_hits(hits: list[Hit]) -> str:
    return json.dumps([h.as_context() for h in hits], ensure_ascii=False)


__all__ = [
    "Embedder",
    "HashingEmbedder",
    "Hit",
    "StandardsIndexError",
    "LocalEmbedder",
    "NoEmbedder",
    "OpenAIEmbedder",
    "StandardsIndex",
    "corpus_fingerprint",
    "dumps_hits",
]
