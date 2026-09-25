"""Retrieval over the standards corpus (RAG).

Sections live in ``standards_chunks`` beside everything else Slipwright keeps, with a
keyword index for BM25-style search and, when an embedder is configured, an embedding per
section for semantic search; ``search`` merges both. Indexing is incremental by chunk id
(a content hash), so unchanged sections are never re-embedded.

The keyword half is the only thing that differs between SQLite and PostgreSQL, and it
lives in ``standards/fts.py``. Chroma, pgvector or Qdrant can replace this class behind
the same ``search`` / ``reindex`` surface if a corpus ever outgrows it.
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx
from sqlalchemy import Integer, case, delete, func, insert, select

from slipwright.standards import Chunk, Page, chunk_corpus, fts
from slipwright.store.db import Database, one, rows
from slipwright.store.schema import standards_chunks, standards_fingerprints

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
            for tok in fts.words(text):
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


def corpus_fingerprint(paths: list[Path]) -> str:
    """Cheap change detector over the files of a corpus (names, sizes, mtimes)."""
    parts = []
    for path in sorted(paths):
        st = path.stat()
        parts.append(f"{path.as_posix()}:{st.st_size}:{st.st_mtime_ns}")
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


class StandardsIndex:
    """The corpus as the roles meet it: sections, scored against a question.

    ``target`` is a ``Database`` (the installation's own, which is the normal case) or a
    path, which opens a SQLite file of its own -- what the tests and a stand-alone index
    do.
    """

    def __init__(self, target: Database | Path | str, embedder: Embedder | None = None) -> None:
        self.db = target if isinstance(target, Database) else Database(target)
        self.path = None if isinstance(target, Database) else Path(str(target))
        self.embedder: Embedder = embedder or NoEmbedder()
        self.db.create_all()
        with self.db.begin() as conn:
            fts.create(conn, self.db.dialect)

    def close(self) -> None:
        # a Database handed in from outside belongs to its owner
        if self.path is not None:
            self.db.dispose()

    # -- indexing ------------------------------------------------------------------------

    def reindex(
        self,
        pages: list[Page],
        *,
        project_id: str | None = None,
        owner_id: str | None = None,
    ) -> dict[str, int]:
        """Index ``pages`` for one layer, replacing whatever that layer held.

        Three layers exist and exactly one is addressed per call: the pages that ship with
        Slipwright (neither argument), the pages one account rewrote (``owner_id``), and a
        project's own overrides (``project_id``). Insert what is new, embed only that, drop
        what is gone, keep the rest.
        """
        wanted = {c.id: c for c in chunk_corpus(pages)}
        order = {cid: i for i, cid in enumerate(wanted)}
        scope = self._scope_clause(project_id, owner_id)
        with self.db.connect() as conn:
            existing = {
                r["id"]: r["embedder"]
                for r in rows(
                    conn.execute(
                        select(standards_chunks.c.id, standards_chunks.c.embedder).where(*scope)
                    )
                )
            }
        stale = [cid for cid in existing if cid not in wanted]
        # re-embed chunks indexed with a different embedder
        new_ids = [
            cid for cid in wanted if cid not in existing or existing[cid] != self.embedder.name
        ]
        new_chunks = [wanted[cid] for cid in new_ids]
        vectors = self.embedder.embed([c.document for c in new_chunks])
        with self.db.begin() as conn:
            for cid in stale + [c.id for c in new_chunks if c.id in existing]:
                conn.execute(delete(standards_chunks).where(standards_chunks.c.id == cid))
                fts.drop_chunk(conn, self.db.dialect, cid)
            for chunk, vec in zip(new_chunks, vectors, strict=True):
                tags = " ".join(chunk.tags)
                conn.execute(
                    insert(standards_chunks).values(
                        id=chunk.id,
                        scope="user" if owner_id else chunk.scope,
                        project_id=project_id,
                        owner_id=owner_id,
                        domain=chunk.domain,
                        page=chunk.page,
                        title=chunk.title,
                        heading=chunk.heading,
                        text=chunk.text,
                        tags=tags,
                        embedder=self.embedder.name,
                        embedding=_pack(vec) if vec else None,
                        seq=order[chunk.id],
                    )
                )
                fts.index_chunk(
                    conn,
                    self.db.dialect,
                    chunk_id=chunk.id,
                    heading=f"{chunk.title} {chunk.heading}",
                    body=chunk.text,
                    tags=tags,
                )
        return {"added": len(new_chunks), "removed": len(stale), "total": len(wanted)}

    def fingerprint(self, project_id: str | None) -> str | None:
        with self.db.connect() as conn:
            row = one(
                conn.execute(
                    select(standards_fingerprints.c.value).where(
                        standards_fingerprints.c.scope_key == (project_id or "")
                    )
                )
            )
        return None if row is None else str(row["value"])

    def set_fingerprint(self, project_id: str | None, value: str) -> None:
        with self.db.begin() as conn:
            conn.execute(
                self.db.upsert(
                    standards_fingerprints,
                    {"scope_key": project_id or "", "value": value},
                    key=["scope_key"],
                    update=["value"],
                )
            )

    def stats(self) -> dict[str, Any]:
        with self.db.connect() as conn:
            total = conn.execute(
                select(func.count()).select_from(standards_chunks)
            ).scalar_one()
            per_domain = {
                r["domain"]: r["n"]
                for r in rows(
                    conn.execute(
                        select(standards_chunks.c.domain, func.count().label("n"))
                        .group_by(standards_chunks.c.domain)
                        .order_by(standards_chunks.c.domain)
                    )
                )
            }
            embedded = conn.execute(
                select(func.count())
                .select_from(standards_chunks)
                .where(standards_chunks.c.embedding.is_not(None))
            ).scalar_one()
        return {
            "chunks": int(total),
            "embedded": int(embedded),
            "embedder": self.embedder.name,
            "per_domain": per_domain,
        }

    # -- search --------------------------------------------------------------------------

    def search(
        self,
        query: str,
        domain: str | None = None,
        *,
        k: int = 4,
        project_id: str | None = None,
        owner_id: str | None = None,
    ) -> list[Hit]:
        """Hybrid ranking: keyword search merged with cosine over embeddings (when the
        query and the sections are embedded). Project chunks win ties over global ones."""
        if not query.strip():
            return []
        with self.db.connect() as conn:
            found = shadowed(
                rows(
                    conn.execute(
                        select(standards_chunks).where(
                            *self._visible(domain, project_id, owner_id)
                        )
                    )
                )
            )
            if not found:
                return []
            keyword = fts.scores(
                conn, self.db.dialect, query, ids=[r["id"] for r in found]
            )
        semantic: dict[str, float] = {}
        if not isinstance(self.embedder, NoEmbedder):
            (qvec,) = self.embedder.embed([query])
            for r in found:
                if r["embedding"] is not None:
                    semantic[r["id"]] = _cosine(qvec, _unpack(r["embedding"]))
        kw_n = _normalise(keyword)
        sem_n = _normalise(semantic)
        # reciprocal rank fusion: robust to the two signals living on different scales
        fused = _rrf(keyword, semantic)
        hits: list[Hit] = []
        for r in found:
            if r["id"] not in keyword and r["id"] not in semantic:
                continue
            kw, sem = kw_n.get(r["id"], 0.0), sem_n.get(r["id"], 0.0)
            score = fused[r["id"]]
            if r["scope"] == "project":
                score += 0.05
            hits.append(Hit(chunk=self._chunk(r), score=score, keyword=kw, semantic=sem))
        hits.sort(key=lambda h: (-h.score, h.chunk.page, h.chunk.heading))
        return hits[:k]

    def browse(
        self,
        domain: str | None = None,
        *,
        k: int = 4,
        project_id: str | None = None,
        owner_id: str | None = None,
    ) -> list[Hit]:
        """The first ``k`` sections of a domain in page order, project pages first: what
        a role reads when nothing in its domain matches the query."""
        # project pages first, then global, then page order within each
        query = (
            select(standards_chunks)
            .where(*self._visible(domain, project_id, owner_id))
            .order_by(_LAYER_ORDER, standards_chunks.c.page, standards_chunks.c.seq)
        )
        with self.db.connect() as conn:
            found = shadowed(rows(conn.execute(query)))[:k]
        return [Hit(chunk=self._chunk(r), score=0.0, keyword=0.0, semantic=0.0) for r in found]

    # -- helpers -------------------------------------------------------------------------

    @staticmethod
    def _chunk(r: Mapping[str, Any]) -> Chunk:
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
    def _visible(
        domain: str | None, project_id: str | None, owner_id: str | None = None
    ) -> list[Any]:
        """The three layers a reader sees at once.

        The pages Slipwright ships, plus the ones this account rewrote, plus this
        project's own overrides. A rewritten page does not replace the shipped one here --
        ``search`` and ``browse`` rank them, and ``shadowed`` drops the shipped copy of
        anything the account has its own version of.
        """
        where: list[Any] = [
            (standards_chunks.c.scope == "global")
            | (
                (standards_chunks.c.scope == "user")
                & (standards_chunks.c.owner_id == (owner_id or ""))
            )
            | (
                (standards_chunks.c.scope == "project")
                & (standards_chunks.c.project_id == (project_id or ""))
            )
        ]
        if domain and domain != "*":
            where.append(standards_chunks.c.domain == domain)
        return where

    @staticmethod
    def _scope_clause(project_id: str | None, owner_id: str | None = None) -> list[Any]:
        """The one layer ``reindex`` replaces wholesale."""
        if owner_id is not None:
            return [
                standards_chunks.c.scope == "user",
                standards_chunks.c.owner_id == owner_id,
            ]
        if project_id is None:
            return [standards_chunks.c.scope == "global"]
        return [
            standards_chunks.c.scope == "project",
            standards_chunks.c.project_id == project_id,
        ]


#: Most specific first. A project's own page outranks the account's, which outranks the
#: one Slipwright ships -- the same order ``shadowed`` drops duplicates in.
_LAYER_ORDER = case(
    (standards_chunks.c.scope == "project", 0),
    (standards_chunks.c.scope == "user", 1),
    else_=2,
).cast(Integer)


def shadowed(found: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Keep the most specific version of each page and drop the rest.

    Rewriting a page means replacing it, not adding a second opinion: an account that has
    its own ``backend/services-and-apis`` must not have the shipped one read to its agents
    as well, or the two would contradict each other inside one prompt.
    """
    rank = {"project": 0, "user": 1, "global": 2}
    best: dict[tuple[str, str], dict[str, Any]] = {}
    for row in found:
        key = (str(row["domain"]), str(row["page"]))
        winner = best.get(key)
        if winner is None or rank.get(str(row["scope"]), 9) < rank.get(str(winner["scope"]), 9):
            best[key] = dict(row)
    keep = {(r["domain"], r["page"]) for r in best.values()}

    def wins(row: Mapping[str, Any]) -> bool:
        key = (row["domain"], row["page"])
        return key in keep and row["scope"] == best[key]["scope"]

    return [dict(r) for r in found if wins(r)]


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
