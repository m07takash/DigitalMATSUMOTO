"""Chat-history storage backends for DigiMSession.

The chat_memory dict has always been a single JSON blob per session on disk.
That works fine for small sessions but read/write cost scales linearly with
the number of turns because the whole file is parsed and rewritten every
call. This module lets operators pick a different backend without changing
any of the DigiMSession call sites.

setting.yaml key:

    SESSION_STORE_METHOD: "JSON"       # default; existing on-disk behaviour
                       or "PostgreSQL"  # digim_chat_history table (JSONB per turn)
                       or "CosmosDB"    # Azure Cosmos DB (doc per turn)

All three implementations expose the same three primitives so the caller
never has to know which backend is active:

    exists(session_id)              -> bool
    load(session_id)                -> dict  # same shape as chat_memory.json
    save(session_id, chat_history_dict, folder_path=None)  # atomic replace

Hybrid coexistence: FileSessionStore always wins if a session's on-disk
`chat_memory.json` exists — even when the configured backend is PG/Cosmos.
That keeps legacy sessions readable after a switch, and new sessions land
in whichever backend is configured. There's a companion migrate CLI users
can run when they want to move old JSON sessions into the DB (deferred —
sketch only for now).

Connection resources (psycopg2 connection, Cosmos client) are lazy-created
per-process and cached; DB backends fall back to JSON with a warning if
their client library isn't installed or credentials are missing, so a
misconfigured deployment degrades to the safe default rather than
crashing every session read.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

import DigiM_Util as dmu

logger = logging.getLogger(__name__)

_setting = dmu.read_yaml_file("setting.yaml") or {}
_STORE_METHOD_DEFAULT = "JSON"


# --------------------------------------------------------------------- ABC --
class SessionStore(ABC):
    """Minimal contract every chat-history backend implements. Returns the
    full nested dict matching the on-disk `chat_memory.json` shape so that
    downstream code (get_history_active / get_memory / save_history_batch)
    keeps operating on the same in-memory structure regardless of storage."""

    method_name: str = "abstract"

    @abstractmethod
    def exists(self, session_id: str) -> bool: ...
    @abstractmethod
    def load(self, session_id: str) -> dict: ...
    @abstractmethod
    def save(self, session_id: str, chat_history_dict: dict,
             folder_path: Optional[str] = None) -> None: ...

    # Convenience — default O(N) full-load implementation is fine for most
    # backends; PG/Cosmos overrides can pull just the row(s) they need.
    def load_seq(self, session_id: str, seq: str) -> dict:
        return (self.load(session_id) or {}).get(str(seq), {}) or {}


# ------------------------------------------------------------- File store --
class FileSessionStore(SessionStore):
    """The historical behaviour — one JSON file per session under
    `user/<prefix><session_id>/chat_memory.json`. Preserved as-is so
    JSON mode is a true no-op vs the previous release."""

    method_name = "JSON"

    def __init__(self):
        s = _setting
        self._user_folder = s.get("USER_FOLDER", "user/")
        self._prefix = s.get("SESSION_FOLDER_PREFIX", "session")
        self._file_name = s.get("SESSION_FILE_NAME", "chat_memory.json")

    def _path(self, session_id: str, folder_path: Optional[str] = None) -> str:
        if folder_path:
            return str(Path(folder_path) / self._file_name)
        return str(Path(self._user_folder) / f"{self._prefix}{session_id}" / self._file_name)

    def exists(self, session_id: str, folder_path: Optional[str] = None) -> bool:
        return os.path.exists(self._path(session_id, folder_path))

    def load(self, session_id: str, folder_path: Optional[str] = None) -> dict:
        p = self._path(session_id, folder_path)
        if not os.path.exists(p):
            return {}
        return dmu.read_json_file(p) or {}

    def save(self, session_id: str, chat_history_dict: dict,
             folder_path: Optional[str] = None) -> None:
        p = self._path(session_id, folder_path)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        dmu.save_json_file(chat_history_dict, p, indent=4)


# --------------------------------------------------------- row helpers --
def iter_rows(chat_history_dict: dict):
    """(seq, sub_seq, value) for every storable entry; SETTING is sub_seq 0."""
    for seq_str, seq_bucket in (chat_history_dict or {}).items():
        try:
            seq_i = int(seq_str)
        except (TypeError, ValueError):
            continue
        for sub_key, sub_val in (seq_bucket or {}).items():
            if sub_key == "SETTING":
                sub_i = 0
            else:
                try:
                    sub_i = int(sub_key)
                except (TypeError, ValueError):
                    continue
            yield seq_i, sub_i, sub_val


def rows_to_history(rows) -> dict:
    result: dict = {}
    for seq, sub_seq, data in rows:
        bucket = result.setdefault(str(seq), {})
        if int(sub_seq) == 0:
            bucket["SETTING"] = data
        else:
            bucket[str(sub_seq)] = data
    return result


def row_json(value) -> str:
    # Sorted and compact so the same content always serialises the same way;
    # the hash below compares rows by this text. JSONB ignores key order.
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def row_hash(text: str) -> str:
    import hashlib
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


# ------------------------------------------------------- PostgreSQL store --
_PG_DDL = """
-- Runtime chat-history storage. Kept separate from digim_dialogs / digim_sessions
-- (the analytics export mirror) so schema evolution here doesn't break
-- the export pipeline. Row per (seq, sub_seq) with the payload in JSONB.
-- sub_seq = 0 encodes the per-seq SETTING; sub_seq >= 1 is a dialog turn.
CREATE TABLE IF NOT EXISTS digim_chat_history (
    session_id  TEXT      NOT NULL,
    seq         INTEGER   NOT NULL,
    sub_seq     INTEGER   NOT NULL,   -- 0 = SETTING row, 1..N = dialog turn
    data        JSONB     NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (session_id, seq, sub_seq)
);
CREATE INDEX IF NOT EXISTS idx_digim_chat_history_session
    ON digim_chat_history (session_id);
CREATE INDEX IF NOT EXISTS idx_digim_chat_history_session_seq
    ON digim_chat_history (session_id, seq DESC);
"""


def pg_connect_kwargs() -> dict:
    """psycopg2.connect() arguments from POSTGRES_* in the environment.

    Shared with the master-data store so the two stores cannot drift on
    SSL handling: POSTGRES_SSLMODE wins, else SSL is required unless
    POSTGRES_REQUIRE_SSL turns it off.
    """
    cfg = {
        "host":     os.getenv("POSTGRES_HOST"),
        "port":     int(os.getenv("POSTGRES_PORT") or 5432),
        "dbname":   os.getenv("POSTGRES_DB"),
        "user":     os.getenv("POSTGRES_USER"),
        "password": os.getenv("POSTGRES_PASSWORD"),
    }
    _ssl = os.getenv("POSTGRES_SSLMODE")
    if _ssl:
        cfg["sslmode"] = _ssl
    elif os.getenv("POSTGRES_REQUIRE_SSL", "1") not in ("0", "false", "False"):
        cfg["sslmode"] = "require"
    return cfg


class PgSessionStore(SessionStore):
    """PostgreSQL backend. One row per (session_id, seq, sub_seq), payload
    in a JSONB column so the outward-facing dict shape remains identical to
    JSON mode. Load rebuilds the full nested dict; save does a diff against
    the current DB state and only UPSERTs / DELETEs the rows that changed —
    which is where the wall-clock win over rewriting a big JSON file comes
    from."""

    method_name = "PostgreSQL"
    table = "digim_chat_history"

    def __init__(self):
        try:
            import psycopg2 as _pg  # noqa: F401
            self._pg_ok = True
        except Exception as _e:
            logger.warning(
                "SESSION_STORE_METHOD=PostgreSQL but psycopg2 is not installed "
                "(%s). Falling back to JSON store for this process.", _e)
            self._pg_ok = False
        # Connection is lazy so a misconfigured env doesn't blow up module load.
        self._conn = None
        self._conn_lock = threading.Lock()
        self._ddl_done = False
        self._fallback = FileSessionStore()
        # session_id -> {(seq, sub_seq): sha1 of the row as last written}.
        # Lets save() send only the rows that changed; see save().
        self._row_hashes: dict = {}

    def forget(self, session_id: str) -> None:
        """Drop the remembered row hashes, for a caller that wrote the table
        directly (archive restore / purge)."""
        with self._conn_lock:
            self._row_hashes.pop(session_id, None)

    def _connect(self):
        # `closed` flips only when psycopg2 itself noticed the drop; _cursor()
        # validates the live ones.
        if self._conn is not None and getattr(self._conn, "closed", 1) == 0:
            return self._conn
        self._conn = None
        import psycopg2
        self._conn = psycopg2.connect(**pg_connect_kwargs())
        self._conn.autocommit = True
        return self._conn

    def _cursor(self):
        # A cached connection can be dead (server restart, idle timeout, network
        # blip) and psycopg2 only reports it once a statement runs. Validate and
        # reconnect once here: without it the caller falls back to the file
        # store, which has no rows for a PG-era session and so reads as an empty
        # conversation — a silent data-loss look.
        last = None
        for attempt in (1, 2):
            conn = self._connect()
            try:
                cur = conn.cursor()
                cur.execute("SELECT 1")
                cur.fetchone()
                if not self._ddl_done:
                    cur.execute(_PG_DDL)
                    self._ddl_done = True
                return cur
            except Exception as _e:
                last = _e
                try:
                    conn.close()
                except Exception:
                    pass
                self._conn = None
                self._ddl_done = False
                if attempt == 2:
                    raise last

    def _fresh(self):
        # A functional cursor, or (with SESSION_STORE_FALLBACK=file) the file
        # store; see _fallback_mode for why the default refuses the latter.
        if not self._pg_ok:
            if _fallback_mode() != "file":
                raise _unreachable("PostgreSQL", "psycopg2 is not installed")
            return None, self._fallback
        try:
            return self._cursor(), None
        except Exception as _e:
            self._last_error = _e
            if _fallback_mode() != "file":
                raise _unreachable("PostgreSQL", _e)
            # Reads then come back empty (a PG-era session has no local file),
            # so this must be loud enough to explain a blank history.
            logger.error("PgSessionStore: connect failed (%s); using file store "
                         "for this call — history of PG-stored sessions will "
                         "read as empty until the DB is reachable.", _e)
            return None, self._fallback

    def exists(self, session_id: str, folder_path: Optional[str] = None) -> bool:
        cur, fb = self._fresh()
        if fb:
            return fb.exists(session_id, folder_path)
        try:
            with self._conn_lock:
                cur.execute(
                    f"SELECT 1 FROM {self.table} WHERE session_id=%s LIMIT 1",
                    (session_id,))
                return cur.fetchone() is not None
        finally:
            try: cur.close()
            except Exception: pass

    def load(self, session_id: str, folder_path: Optional[str] = None) -> dict:
        cur, fb = self._fresh()
        if fb:
            return fb.load(session_id, folder_path)
        try:
            with self._conn_lock:
                cur.execute(f"""
                    SELECT seq, sub_seq, data FROM {self.table}
                    WHERE session_id=%s
                    ORDER BY seq, sub_seq
                """, (session_id,))
                rows = cur.fetchall()
        finally:
            try: cur.close()
            except Exception: pass
        return rows_to_history(rows)

    def save(self, session_id: str, chat_history_dict: dict,
             folder_path: Optional[str] = None) -> None:
        cur, fb = self._fresh()
        if fb:
            _log_file_fallback("PostgreSQL", session_id, getattr(self, "_last_error", "driver missing"))
            fb.save(session_id, chat_history_dict, folder_path); return
        # The caller always hands over the whole session, and writing all of
        # it back cost 11.5 s for a 216-row / 29.7 MB session (0.06 s for the
        # one row that had changed) — on every turn, feedback, memory flag and
        # analytics save. Rows are compared by hash against what this process
        # last wrote, and only the ones that differ are sent.
        desired: dict = {}
        texts: dict = {}
        for seq_i, sub_i, sub_val in iter_rows(chat_history_dict):
            t = row_json(sub_val)
            texts[(seq_i, sub_i)] = t
            desired[(seq_i, sub_i)] = row_hash(t)
        try:
            with self._conn_lock:
                known = self._row_hashes.get(session_id)
                if known is None:
                    # First save of this session in this process: compare
                    # against the stored rows once (a read, far cheaper than
                    # rewriting them), then remember the hashes.
                    cur.execute(f"SELECT seq, sub_seq, data FROM {self.table} WHERE session_id=%s",
                                (session_id,))
                    known = {(r[0], r[1]): row_hash(row_json(r[2])) for r in cur.fetchall()}
                    existing = set(known)
                else:
                    # The keyset is still read from the table so rows that
                    # are gone from the dict are removed, as before.
                    cur.execute(f"SELECT seq, sub_seq FROM {self.table} WHERE session_id=%s",
                                (session_id,))
                    existing = {(r[0], r[1]) for r in cur.fetchall()}
                changed = [k for k, h in desired.items()
                           if k not in existing or known.get(k) != h]
                to_delete = existing - set(desired)
                if to_delete:
                    cur.executemany(
                        f"DELETE FROM {self.table} WHERE session_id=%s AND seq=%s AND sub_seq=%s",
                        [(session_id, s, ss) for s, ss in to_delete])
                if changed:
                    cur.executemany(f"""
                        INSERT INTO {self.table} (session_id, seq, sub_seq, data, updated_at)
                        VALUES (%s, %s, %s, %s::jsonb, NOW())
                        ON CONFLICT (session_id, seq, sub_seq)
                        DO UPDATE SET data = EXCLUDED.data, updated_at = NOW()
                    """, [(session_id, s, ss, texts[(s, ss)]) for s, ss in changed])
                self._row_hashes[session_id] = desired
        except Exception:
            # Unknown how far the write got, so the next save re-reads.
            with self._conn_lock:
                self._row_hashes.pop(session_id, None)
            raise
        finally:
            try: cur.close()
            except Exception: pass


# -------------------------------------------------------- DB unreachable --
def _fallback_mode() -> str:
    """SESSION_STORE_FALLBACK in setting.yaml: "none" (default) or "file".

    Falling back to the file store while the DB is down reads a PG-era session
    as empty, and the next turn then writes a chat_memory.json holding only
    that turn. Hybrid reads prefer the file from then on, so once the DB is
    back the session shows the outage turns alone and the rest of the
    conversation looks lost. "none" fails the call instead.
    """
    m = str(_setting.get("SESSION_STORE_FALLBACK") or "none").strip().lower()
    return "file" if m == "file" else "none"


def _unreachable(store: str, err) -> RuntimeError:
    return RuntimeError(
        f"{store} session store is unreachable ({err}). Refusing to use the local file store "
        f"instead (SESSION_STORE_FALLBACK=none), because that splits the session's history.")


def _log_file_fallback(store: str, session_id: str, err) -> None:
    logger.error("%s unreachable (%s): session %s was written to the local file store; it is "
                 "read from that file from now on, so import it back once the DB is reachable.",
                 store, err, session_id)


# ---------------------------------------------------------- Cosmos store --
class CosmosSessionStore(SessionStore):
    """Azure Cosmos DB (SQL API) backend. Container must exist beforehand
    with partition key `/session_id`. Documents are keyed
    `id = "{seq}-{sub_seq}"` (sub_seq=0 for the SETTING doc). The
    outward-facing dict shape is the same as JSON/PG modes."""

    method_name = "CosmosDB"

    def __init__(self):
        try:
            from azure.cosmos import CosmosClient  # noqa: F401
            self._sdk_ok = True
        except Exception as _e:
            logger.warning(
                "SESSION_STORE_METHOD=CosmosDB but azure-cosmos is not "
                "installed (%s). Falling back to JSON store.", _e)
            self._sdk_ok = False
        self._container = None
        self._conn_lock = threading.Lock()
        self._fallback = FileSessionStore()
        _s = _setting or {}
        self._db_name = os.getenv("COSMOS_DATABASE") or _s.get("COSMOS_DATABASE", "digimatsu")
        self._container_name = os.getenv("COSMOS_CONTAINER") or _s.get("COSMOS_CONTAINER", "chat_history")
        self._row_hashes: dict = {}

    def forget(self, session_id: str) -> None:
        with self._conn_lock:
            self._row_hashes.pop(session_id, None)

    def _client(self):
        if self._container is not None:
            return self._container
        from azure.cosmos import CosmosClient
        endpoint = os.getenv("COSMOS_ENDPOINT")
        key = os.getenv("COSMOS_KEY")
        if not endpoint or not key:
            raise RuntimeError(
                "CosmosSessionStore: COSMOS_ENDPOINT / COSMOS_KEY env vars required")
        client = CosmosClient(endpoint, credential=key)
        db = client.get_database_client(self._db_name)
        self._container = db.get_container_client(self._container_name)
        return self._container

    def _fresh(self):
        if not self._sdk_ok:
            if _fallback_mode() != "file":
                raise _unreachable("Cosmos DB", "azure-cosmos is not installed")
            return None, self._fallback
        try:
            return self._client(), None
        except Exception as _e:
            if _fallback_mode() != "file":
                raise _unreachable("Cosmos DB", _e)
            logger.warning("CosmosSessionStore: connect failed (%s); "
                           "using file store for this call.", _e)
            return None, self._fallback

    def exists(self, session_id: str, folder_path: Optional[str] = None) -> bool:
        c, fb = self._fresh()
        if fb: return fb.exists(session_id, folder_path)
        try:
            items = list(c.query_items(
                query="SELECT VALUE c.id FROM c WHERE c.session_id=@s OFFSET 0 LIMIT 1",
                parameters=[{"name": "@s", "value": session_id}],
                partition_key=session_id))
            return bool(items)
        except Exception as _e:
            if _fallback_mode() != "file":
                raise _unreachable("Cosmos DB", _e)
            logger.warning("Cosmos exists() failed: %s", _e); return False

    def load(self, session_id: str, folder_path: Optional[str] = None) -> dict:
        c, fb = self._fresh()
        if fb: return fb.load(session_id, folder_path)
        try:
            items = list(c.query_items(
                query="SELECT * FROM c WHERE c.session_id=@s",
                parameters=[{"name": "@s", "value": session_id}],
                partition_key=session_id))
        except Exception as _e:
            # An empty dict here reads as "no history" and the next save would
            # start the conversation over.
            if _fallback_mode() != "file":
                raise _unreachable("Cosmos DB", _e)
            logger.warning("Cosmos load() failed: %s", _e); return {}
        result: dict = {}
        for it in items:
            seq = it.get("seq"); sub_seq = it.get("sub_seq")
            data = it.get("data", {})
            if seq is None or sub_seq is None:
                continue
            bucket = result.setdefault(str(seq), {})
            if int(sub_seq) == 0:
                bucket["SETTING"] = data
            else:
                bucket[str(sub_seq)] = data
        return result

    def save(self, session_id: str, chat_history_dict: dict,
             folder_path: Optional[str] = None) -> None:
        c, fb = self._fresh()
        if fb:
            _log_file_fallback("Cosmos DB", session_id, "connect failed")
            fb.save(session_id, chat_history_dict, folder_path); return
        # Same reasoning as PgSessionStore.save: every upsert is billed in RU,
        # so only rows whose content changed are written.
        desired: dict = {}
        for seq_i, sub_i, sub_val in iter_rows(chat_history_dict):
            desired[(seq_i, sub_i)] = (row_hash(row_json(sub_val)), sub_val)
        try:
            with self._conn_lock:
                known = self._row_hashes.get(session_id)
            if known is None:
                known = {}
                existing = set()
                for it in c.query_items(
                        query="SELECT c.seq, c.sub_seq, c.data FROM c WHERE c.session_id=@s",
                        parameters=[{"name": "@s", "value": session_id}],
                        partition_key=session_id):
                    k = (int(it["seq"]), int(it["sub_seq"]))
                    existing.add(k)
                    known[k] = row_hash(row_json(it.get("data", {})))
            else:
                existing = set()
                for it in c.query_items(
                        query="SELECT c.seq, c.sub_seq FROM c WHERE c.session_id=@s",
                        parameters=[{"name": "@s", "value": session_id}],
                        partition_key=session_id):
                    existing.add((int(it["seq"]), int(it["sub_seq"])))
            for (seq_i, sub_i), (h, sub_val) in desired.items():
                if (seq_i, sub_i) in existing and known.get((seq_i, sub_i)) == h:
                    continue
                c.upsert_item({
                    "id": f"{seq_i}-{sub_i}",
                    "session_id": session_id,
                    "seq": seq_i,
                    "sub_seq": sub_i,
                    "data": sub_val,
                })
            for seq_i, sub_i in (existing - set(desired)):
                try:
                    c.delete_item(item=f"{seq_i}-{sub_i}", partition_key=session_id)
                except Exception:
                    pass
            with self._conn_lock:
                self._row_hashes[session_id] = {k: v[0] for k, v in desired.items()}
        except Exception as _e:
            with self._conn_lock:
                self._row_hashes.pop(session_id, None)
            if _fallback_mode() != "file":
                raise _unreachable("Cosmos DB", _e)
            _log_file_fallback("Cosmos DB", session_id, _e)
            self._fallback.save(session_id, chat_history_dict, folder_path)


# --------------------------------------------------------------- factory --
_STORE_INSTANCE: Optional[SessionStore] = None
_STORE_INSTANCE_LOCK = threading.Lock()


def _resolve_method() -> str:
    m = (_setting.get("SESSION_STORE_METHOD") or _STORE_METHOD_DEFAULT).strip()
    m_norm = m.lower()
    if m_norm in ("json", "file"):
        return "JSON"
    if m_norm in ("postgresql", "postgres", "pg"):
        return "PostgreSQL"
    if m_norm in ("cosmosdb", "cosmos"):
        return "CosmosDB"
    logger.warning("Unknown SESSION_STORE_METHOD=%r; defaulting to JSON.", m)
    return "JSON"


def get_store() -> SessionStore:
    """Cached process-wide store. First call determines the backend based
    on setting.yaml; subsequent calls return the same instance."""
    global _STORE_INSTANCE
    if _STORE_INSTANCE is not None:
        return _STORE_INSTANCE
    with _STORE_INSTANCE_LOCK:
        if _STORE_INSTANCE is not None:
            return _STORE_INSTANCE
        method = _resolve_method()
        if method == "PostgreSQL":
            _STORE_INSTANCE = PgSessionStore()
        elif method == "CosmosDB":
            _STORE_INSTANCE = CosmosSessionStore()
        else:
            _STORE_INSTANCE = FileSessionStore()
        logger.info("SessionStore selected: %s", _STORE_INSTANCE.method_name)
        return _STORE_INSTANCE


# ---------------------------------------------------- hybrid read helper --
_FILE_STORE_SINGLETON: Optional[FileSessionStore] = None


def _file_store() -> FileSessionStore:
    """Always-available FileSessionStore so hybrid reads (legacy JSON
    sessions still on disk after switching to PG/Cosmos) keep working."""
    global _FILE_STORE_SINGLETON
    if _FILE_STORE_SINGLETON is None:
        _FILE_STORE_SINGLETON = FileSessionStore()
    return _FILE_STORE_SINGLETON


def load_history(session_id: str, folder_path: Optional[str] = None) -> dict:
    """DigiMSession's read entry point. Prefers a legacy on-disk
    chat_memory.json when it exists (so old sessions remain readable after
    switching to PG/Cosmos), otherwise routes to the configured backend."""
    fs = _file_store()
    if fs.exists(session_id, folder_path):
        return fs.load(session_id, folder_path)
    return get_store().load(session_id, folder_path)


def save_history(session_id: str, chat_history_dict: dict,
                  folder_path: Optional[str] = None) -> None:
    """DigiMSession's write entry point. If the session already exists as
    an on-disk file, write back to that file (keeps hybrid sessions
    consistent). Otherwise write to the configured backend."""
    fs = _file_store()
    if fs.exists(session_id, folder_path):
        fs.save(session_id, chat_history_dict, folder_path)
        return
    get_store().save(session_id, chat_history_dict, folder_path)


def history_exists(session_id: str, folder_path: Optional[str] = None) -> bool:
    if _file_store().exists(session_id, folder_path):
        return True
    return get_store().exists(session_id, folder_path)
