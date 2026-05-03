"""SQLite-backed knowledge chunks with Ollama embeddings (using sqlite-vec)."""
from __future__ import annotations

import re
import sqlite3
import struct
import threading
from pathlib import Path

import sqlite_vec

from backend.config import settings

from .embeddings_client import embed_one

_lock = threading.Lock()
_ingested_flag = False

_CHUNK_RE = re.compile(r"\n{2,}|\n(?=#)")
_META_KEY_DIM = "embedding_dim"


def _db_path() -> Path:
    p = settings.data_dir / "rag_knowledge.sqlite"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _serialize_f32(vector: list[float]) -> bytes:
    return struct.pack(f"{len(vector)}f", *vector)


def _resolve_embedding_dim(conn: sqlite3.Connection) -> int:
    """Prefer live probe; if Ollama is down, keep last stored dimension or default."""
    e = embed_one("__shadow_embedding_dim_probe__")
    if e and len(e) > 0:
        return len(e)
    stored = _get_stored_dim(conn)
    if stored and stored > 0:
        return stored
    return 3072


def _get_stored_dim(conn: sqlite3.Connection) -> int | None:
    try:
        row = conn.execute(
            "SELECT v FROM rag_meta WHERE k = ?",
            (_META_KEY_DIM,),
        ).fetchone()
        if row and str(row[0]).isdigit():
            return int(row[0])
    except sqlite3.OperationalError:
        pass
    return None


def _set_stored_dim(conn: sqlite3.Connection, dim: int) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS rag_meta (
            k TEXT PRIMARY KEY NOT NULL,
            v TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "INSERT OR REPLACE INTO rag_meta (k, v) VALUES (?, ?)",
        (_META_KEY_DIM, str(dim)),
    )


def _vec_table_exists(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='vec_knowledge_chunks'"
    ).fetchone()
    return row is not None


def _drop_vector_sidecars(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TABLE IF EXISTS vec_knowledge_chunks")
    conn.execute("DROP TABLE IF EXISTS fts_knowledge_chunks")


def _create_vec_and_fts(conn: sqlite3.Connection, dim: int) -> None:
    conn.execute(
        f"""
        CREATE VIRTUAL TABLE vec_knowledge_chunks USING vec0(
            embedding float[{dim}]
        )
        """
    )
    conn.execute(
        """
        CREATE VIRTUAL TABLE fts_knowledge_chunks USING fts5(
            text,
            source UNINDEXED,
            content='knowledge_chunks',
            content_rowid='id'
        )
        """
    )


def _init_schema(conn: sqlite3.Connection) -> int:
    """Ensure base tables and vec/FTS exist for the current embedding dimension. Returns dim."""
    global _ingested_flag
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            text TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE TABLE IF NOT EXISTS rag_meta (k TEXT PRIMARY KEY NOT NULL, v TEXT NOT NULL)")

    dim = _resolve_embedding_dim(conn)
    stored = _get_stored_dim(conn)
    vec_ok = _vec_table_exists(conn)

    if not vec_ok or stored is None or stored != dim:
        _drop_vector_sidecars(conn)
        conn.execute("DELETE FROM knowledge_chunks")
        _create_vec_and_fts(conn, dim)
        _set_stored_dim(conn, dim)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_knowledge_source ON knowledge_chunks(source)"
        )
        conn.commit()
        _ingested_flag = False
    else:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_knowledge_source ON knowledge_chunks(source)"
        )
    return dim


def _chunk_text(text: str, max_chars: int = 900, overlap: int = 150) -> list[str]:
    text = text.strip()
    if not text:
        return []
    parts = [p.strip() for p in _CHUNK_RE.split(text) if p.strip()]
    if not parts:
        return [text[:max_chars]]
    out: list[str] = []
    buf = ""
    for p in parts:
        if len(buf) + len(p) + 2 <= max_chars:
            buf = f"{buf}\n\n{p}".strip() if buf else p
        else:
            if buf:
                out.append(buf[:max_chars])
            overlap_text = buf[-overlap:] if len(buf) > overlap else buf
            buf = f"{overlap_text}\n\n{p}".strip() if overlap_text else p
    if buf:
        out.append(buf[:max_chars])
    return out[:200]


def ingest_file(path: Path, *, source_label: str | None = None) -> int:
    """Embed and store chunks from a markdown/text file. Returns rows inserted."""
    if not path.is_file():
        return 0
    raw = path.read_text(encoding="utf-8", errors="replace")
    label = source_label or str(path.name)
    chunks = _chunk_text(raw)
    if not chunks:
        return 0
    db = _db_path()
    conn = sqlite3.connect(str(db))
    try:
        dim = _init_schema(conn)
        rows = conn.execute("SELECT id FROM knowledge_chunks WHERE source = ?", (label,)).fetchall()
        if rows:
            ids = [r[0] for r in rows]
            id_list = ",".join("?" * len(ids))
            conn.execute(f"DELETE FROM vec_knowledge_chunks WHERE rowid IN ({id_list})", ids)
            conn.execute(f"DELETE FROM fts_knowledge_chunks WHERE rowid IN ({id_list})", ids)
            conn.execute("DELETE FROM knowledge_chunks WHERE source = ?", (label,))

        n = 0
        for i, ch in enumerate(chunks):
            emb = embed_one(ch)
            if not emb or len(emb) != dim:
                continue
            cursor = conn.execute(
                "INSERT INTO knowledge_chunks (source, chunk_index, text) VALUES (?,?,?)",
                (label, i, ch),
            )
            rowid = cursor.lastrowid
            conn.execute(
                "INSERT INTO vec_knowledge_chunks (rowid, embedding) VALUES (?, ?)",
                (rowid, _serialize_f32(emb)),
            )
            conn.execute(
                "INSERT INTO fts_knowledge_chunks (rowid, text, source) VALUES (?, ?, ?)",
                (rowid, ch, label),
            )
            n += 1
        conn.commit()
        return n
    finally:
        conn.close()


def default_ingest_paths() -> list[Path]:
    root = Path(__file__).resolve().parents[2]
    paths: list[Path] = []
    p = root / "backend" / "agents" / "fraud_playbook_context.md"
    if p.is_file():
        paths.append(p)
    return paths


def ensure_ingested(*, force: bool = False) -> None:
    """Idempotent ingest of default playbook(s)."""
    global _ingested_flag
    with _lock:
        if _ingested_flag and not force:
            return
        for p in default_ingest_paths():
            ingest_file(p, source_label=p.name)
        _ingested_flag = True


def search_knowledge(query: str, *, top_k: int = 5) -> list[dict]:
    """Hybrid search: Vector similarity (sqlite-vec) + FTS5 BM25 with Reciprocal Rank Fusion (RRF)."""
    ensure_ingested()
    qe = embed_one(query)

    conn = sqlite3.connect(str(_db_path()))
    try:
        dim = _init_schema(conn)

        vec_ranks: dict[int, int] = {}
        if qe and len(qe) == dim:
            vec_rows = conn.execute(
                """
                SELECT rowid, vec_distance_cosine(embedding, ?) as distance
                FROM vec_knowledge_chunks
                ORDER BY distance ASC
                LIMIT 20
                """,
                (_serialize_f32(qe),),
            ).fetchall()
            for rank, (rowid, _dist) in enumerate(vec_rows):
                vec_ranks[rowid] = rank

        fts_ranks: dict[int, int] = {}
        fts_query = " OR ".join(w for w in re.split(r"\W+", query) if len(w) > 2)
        if fts_query:
            try:
                fts_rows = conn.execute(
                    """
                    SELECT rowid, bm25(fts_knowledge_chunks) as score
                    FROM fts_knowledge_chunks
                    WHERE fts_knowledge_chunks MATCH ?
                    ORDER BY score ASC
                    LIMIT 20
                    """,
                    (fts_query,),
                ).fetchall()
                for rank, (rowid, _score) in enumerate(fts_rows):
                    fts_ranks[rowid] = rank
            except sqlite3.OperationalError:
                pass

        k_rrf = 60
        rrf_scores: dict[int, float] = {}
        all_ids = set(vec_ranks.keys()) | set(fts_ranks.keys())

        for rowid in all_ids:
            score = 0.0
            if rowid in vec_ranks:
                score += 1.0 / (k_rrf + vec_ranks[rowid])
            if rowid in fts_ranks:
                score += 1.0 / (k_rrf + fts_ranks[rowid])
            rrf_scores[rowid] = score

        if not rrf_scores:
            return []

        top_ids = sorted(rrf_scores.keys(), key=lambda x: rrf_scores[x], reverse=True)[:top_k]
        id_list = ",".join("?" * len(top_ids))

        results = conn.execute(
            f"""
            SELECT id, source, chunk_index, text
            FROM knowledge_chunks
            WHERE id IN ({id_list})
            """,
            top_ids,
        ).fetchall()

        results_dict = {r[0]: r for r in results}

        return [
            {
                "source": results_dict[rowid][1],
                "chunk_index": results_dict[rowid][2],
                "text": results_dict[rowid][3],
                "score": round(rrf_scores[rowid], 4),
            }
            for rowid in top_ids
            if rowid in results_dict
        ]
    finally:
        conn.close()
