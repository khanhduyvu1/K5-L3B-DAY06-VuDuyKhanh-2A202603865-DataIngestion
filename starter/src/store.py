"""Store and search vectors using PostgreSQL + pgvector (exact cosine search)."""
from __future__ import annotations

import json
from typing import Any

import psycopg
from pgvector.psycopg import register_vector
from psycopg import sql

from .chunking import content_hash
from .models import Chunk

# Only these metadata columns may be used in filters (no free-form SQL).
FILTERABLE = {"year": int, "chuong": int, "document_id": str}


class PgVectorStore:
    def __init__(self, database_url: str, dimensions: int, table: str = "chunks") -> None:
        if not database_url:
            raise ValueError("DATABASE_URL is empty")
        self.database_url = database_url
        self.dimensions = int(dimensions)
        self.table = table

    def _connect(self) -> psycopg.Connection:
        conn = psycopg.connect(self.database_url, connect_timeout=5)
        register_vector(conn)
        return conn

    def create_schema(self) -> None:
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
                "WHERE attrelid = to_regclass(%s) AND attname = 'embedding'", (self.table,)).fetchone()
            if existing and existing[0] != f"vector({self.dimensions})":
                raise ValueError(f"table {self.table} has {existing[0]}, model needs vector({self.dimensions})")
            conn.execute(sql.SQL("""
                CREATE TABLE IF NOT EXISTS {t} (
                    strategy     text    NOT NULL,
                    chunk_id     text    NOT NULL,
                    document_id  text    NOT NULL,
                    source       text    NOT NULL,
                    page         integer NOT NULL,
                    pages        integer[] NOT NULL,
                    year         integer NOT NULL,
                    chuong       integer NOT NULL,
                    text         text    NOT NULL,
                    content_hash text    NOT NULL,
                    metadata     jsonb   NOT NULL,
                    embedding    vector({d}) NOT NULL,
                    ingested_at  timestamptz NOT NULL DEFAULT now(),
                    PRIMARY KEY (strategy, chunk_id)
                )""").format(t=sql.Identifier(self.table), d=sql.Literal(self.dimensions)))
            conn.execute(sql.SQL("CREATE INDEX IF NOT EXISTS {i} ON {t} (strategy, year)").format(
                i=sql.Identifier(f"{self.table}_strategy_year"), t=sql.Identifier(self.table)))

    def existing_hashes(self, strategy: str) -> dict[str, str]:
        with self._connect() as conn:
            rows = conn.execute(sql.SQL("SELECT chunk_id, content_hash FROM {t} WHERE strategy = %s")
                                .format(t=sql.Identifier(self.table)), (strategy,)).fetchall()
        return dict(rows)

    def count(self, strategy: str | None = None) -> int:
        with self._connect() as conn:
            if strategy is None:
                q = sql.SQL("SELECT count(*) FROM {t}").format(t=sql.Identifier(self.table))
                return conn.execute(q).fetchone()[0]
            q = sql.SQL("SELECT count(*), count(DISTINCT chunk_id) FROM {t} WHERE strategy = %s").format(
                t=sql.Identifier(self.table))
            total, distinct = conn.execute(q, (strategy,)).fetchone()
            if total != distinct:
                raise RuntimeError(f"duplicate chunk ids in {strategy}")
            return total

    def upsert(self, strategy: str, chunks: list[Chunk], vectors: list[list[float]],
               document_ids: list[str], keep_ids: list[str] | None = None) -> dict[str, int]:
        """Insert/update ``chunks`` and delete chunks of ``document_ids`` not in ``keep_ids``.

        ``keep_ids`` defaults to the IDs of ``chunks``; pass the full current set
        when ``chunks`` only holds the new/changed subset.

        ``vectors`` aligns with ``chunks``. Rows whose content hash is unchanged
        are not rewritten. Chunk IDs are deterministic, so re-ingesting the same
        version never creates duplicates.
        """
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors differ in length")
        for v in vectors:
            if len(v) != self.dimensions:
                raise ValueError(f"vector has {len(v)} dims, expected {self.dimensions}")
        import numpy as np

        rows = [(strategy, c.chunk_id, c.document_id, c.source, c.page, c.metadata["pages"],
                 c.metadata["year"], c.metadata["chuong"], c.text, content_hash(c.text),
                 json.dumps(c.metadata, ensure_ascii=False), np.asarray(v, dtype=np.float32))
                for c, v in zip(chunks, vectors)]
        t = sql.Identifier(self.table)
        with self._connect() as conn:
            before = self.count(strategy)
            with conn.cursor() as cur:
                if rows:
                    cur.executemany(sql.SQL("""
                    INSERT INTO {t} (strategy, chunk_id, document_id, source, page, pages, year, chuong,
                                     text, content_hash, metadata, embedding)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (strategy, chunk_id) DO UPDATE SET
                        document_id = EXCLUDED.document_id, source = EXCLUDED.source,
                        page = EXCLUDED.page, pages = EXCLUDED.pages, year = EXCLUDED.year,
                        chuong = EXCLUDED.chuong, text = EXCLUDED.text,
                        content_hash = EXCLUDED.content_hash, metadata = EXCLUDED.metadata,
                        embedding = EXCLUDED.embedding, ingested_at = now()
                    WHERE {t}.content_hash <> EXCLUDED.content_hash""").format(t=t), rows)
                keep = keep_ids if keep_ids is not None else [c.chunk_id for c in chunks]
                cur.execute(sql.SQL("""DELETE FROM {t} WHERE strategy = %s AND document_id = ANY(%s)
                                       AND NOT (chunk_id = ANY(%s))""").format(t=t),
                            (strategy, document_ids, keep))
                deleted = cur.rowcount
        return {"before": before, "written": len(rows), "deleted_stale": deleted, "after": self.count(strategy)}

    def search(self, strategy: str, query_vector: list[float], top_k: int = 3,
               filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Exact cosine search (sequential scan) with optional SQL metadata filter."""
        if len(query_vector) != self.dimensions:
            raise ValueError("query vector dimension mismatch")
        import numpy as np

        where = [sql.SQL("strategy = %s")]
        params: list[Any] = [strategy]
        for key, value in (filters or {}).items():
            if key not in FILTERABLE:
                raise ValueError(f"filter on '{key}' is not allowed")
            where.append(sql.SQL("{} = %s").format(sql.Identifier(key)))
            params.append(FILTERABLE[key](value))
        qv = np.asarray(query_vector, dtype=np.float32)
        query = sql.SQL("""
            SELECT chunk_id, document_id, source, page, pages, year, chuong, text, metadata,
                   1 - (embedding <=> %s) AS score
            FROM {t} WHERE {w} ORDER BY embedding <=> %s LIMIT %s""").format(
            t=sql.Identifier(self.table), w=sql.SQL(" AND ").join(where))
        with self._connect() as conn:
            cur = conn.execute(query, [qv, *params, qv, top_k])
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
