"""Chat-history retention: back sessions up, purge the old ones, restore.

The unit of work is always a whole session. Removing single turns would leave
seq numbering, digests and user memory pointing at turns that no longer exist.

Where a session's history lives is decided per session, not per deployment,
because PostgreSQL / Cosmos mode still reads legacy JSON sessions from disk:

  file      the session folder holds chat_memory.json
  postgres  rows in digim_chat_history
  cosmos    documents in the chat-history container
  none      a folder with no history at all (a New Chat that was never used)

In every backend the session *folder* (status.yaml, vecs/, contents/,
analytics/) stays on disk, so a purge has to remove both the history and the
folder. Removing only one is how a session ends up listed-but-empty, or as
rows nobody can reach.

Operations
  backup   DB backends: copy every session whose live rows changed into the
           archive store (digim_chat_history_archive / the archive container).
           Safe to run on a schedule. With `days`, sessions older than that are
           also written to a ZIP (file sessions only get backed up this way).
  purge    For sessions idle for `days` or more: export to the analytics
           mirror, back up, write a ZIP, verify both, then delete the live
           history and the folder. Nothing is deleted that was not verified.
  restore  Put a purged session back from its ZIP (folder) and the archive
           store (rows), or from the ZIP alone.

ZIP layout (one per run, under ARCHIVE_FOLDER, same as before so the WebUI
download and the Agent section of the Performance Explorer keep reading it):
  session<ID>/...               the folder as it was on disk
  session<ID>/chat_memory.json  the history; written out for DB sessions too
  manifest.json                 what is in the ZIP and how to verify it

CLI:  python3 DigiM_HistoryArchive.py list|backup|purge|restore|archives ...
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sys
import threading
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

import DigiM_Util as dmu
import DigiM_SessionStore as dmss

logger = logging.getLogger(__name__)

_setting = dmu.read_yaml_file("setting.yaml") or {}

if os.path.exists("system.env"):
    from dotenv import load_dotenv
    load_dotenv("system.env")


class _Config:
    """Paths and table names. Tests point these at throwaway locations."""
    def __init__(self):
        self.user_folder = _setting.get("USER_FOLDER", "user/")
        self.prefix = _setting.get("SESSION_FOLDER_PREFIX", "session")
        self.history_file = _setting.get("SESSION_FILE_NAME", "chat_memory.json")
        self.status_file = _setting.get("SESSION_STATUS_FILE_NAME", "status.yaml")
        self.archive_folder = _setting.get("ARCHIVE_FOLDER", "user/archive/")
        self.default_days = int(_setting.get("ARCHIVE_DAYS", 30) or 30)
        self.live_table = dmss.PgSessionStore.table
        self.archive_table = "digim_chat_history_archive"
        self.ledger_table = "digim_chat_history_archive_sessions"
        self.cosmos_archive_container = (os.getenv("COSMOS_ARCHIVE_CONTAINER")
                                         or _setting.get("COSMOS_ARCHIVE_CONTAINER",
                                                         "chat_history_archive"))
        # Analytics mirror table -> its archive copy.
        self.mirror_archive = {"digim_sessions": "digim_sessions_archive",
                               "digim_dialogs": "digim_dialogs_archive",
                               "digim_references": "digim_references_archive",
                               "digim_steps": "digim_steps_archive"}
        # Override for tests: None means "whatever SESSION_STORE_METHOD says".
        self.store_method: Optional[str] = None

    def folder(self, sid: str) -> str:
        return os.path.join(self.user_folder, f"{self.prefix}{sid}")


cfg = _Config()
_run_lock = threading.Lock()
_ZIP_FORMAT = 2


def _store_method() -> str:
    if cfg.store_method:
        return cfg.store_method
    return dmss._resolve_method()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Optional[datetime]) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds") if dt else ""


# ======================================================== DB backends ====
class _PgBackend:
    name = "postgres"

    def __init__(self):
        self._conn = None
        self._ready = False

    def _connect(self):
        if self._conn is not None and getattr(self._conn, "closed", 1) == 0:
            return self._conn
        import psycopg2
        self._conn = psycopg2.connect(**dmss.pg_connect_kwargs())
        self._conn.autocommit = False
        self._ready = False
        return self._conn

    def close(self):
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
        self._conn = None

    def ensure(self):
        conn = self._connect()
        if self._ready:
            return
        with conn.cursor() as cur:
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {cfg.archive_table} (
                    session_id  TEXT        NOT NULL,
                    seq         INTEGER     NOT NULL,
                    sub_seq     INTEGER     NOT NULL,
                    data        JSONB       NOT NULL,
                    created_at  TIMESTAMPTZ NOT NULL,
                    updated_at  TIMESTAMPTZ NOT NULL,
                    archived_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (session_id, seq, sub_seq)
                );
                CREATE TABLE IF NOT EXISTS {cfg.ledger_table} (
                    session_id   TEXT PRIMARY KEY,
                    rows         INTEGER     NOT NULL,
                    content_md5  TEXT        NOT NULL,
                    backed_up_at TIMESTAMPTZ NOT NULL,
                    purged_at    TIMESTAMPTZ,
                    zip_name     TEXT,
                    restored_at  TIMESTAMPTZ
                );
                CREATE INDEX IF NOT EXISTS idx_{cfg.ledger_table}_purged
                    ON {cfg.ledger_table} (purged_at);
            """)
        conn.commit()
        self._ready = True

    def live_stats(self) -> dict:
        self.ensure()
        with self._conn.cursor() as cur:
            cur.execute(f"""SELECT session_id, COUNT(*), MAX(updated_at), SUM(pg_column_size(data))
                            FROM {cfg.live_table} GROUP BY session_id""")
            out = {r[0]: (int(r[1]), r[2], int(r[3] or 0)) for r in cur.fetchall()}
        self._conn.commit()
        return out

    def archive_stats(self) -> dict:
        self.ensure()
        with self._conn.cursor() as cur:
            cur.execute(f"""SELECT session_id, COUNT(*), MAX(updated_at)
                            FROM {cfg.archive_table} GROUP BY session_id""")
            out = {r[0]: (int(r[1]), r[2]) for r in cur.fetchall()}
        self._conn.commit()
        return out

    def ledger(self) -> dict:
        self.ensure()
        with self._conn.cursor() as cur:
            cur.execute(f"SELECT session_id, backed_up_at, purged_at, zip_name, restored_at "
                        f"FROM {cfg.ledger_table}")
            out = {r[0]: {"backed_up_at": _iso(r[1]), "purged_at": _iso(r[2]),
                          "zip_name": r[3] or "", "restored_at": _iso(r[4])}
                   for r in cur.fetchall()}
        self._conn.commit()
        return out

    def _fingerprint(self, cur, table: str, sid: str) -> tuple:
        # JSONB prints canonically, so identical content gives identical text
        # in both tables — a hash over it compares the two without pulling
        # the payload into Python.
        cur.execute(f"""SELECT COUNT(*), COALESCE(md5(string_agg(md5(data::text), '' ORDER BY seq, sub_seq)), '')
                        FROM {table} WHERE session_id=%s""", (sid,))
        n, h = cur.fetchone()
        return int(n), h

    def history(self, sid: str) -> dict:
        self.ensure()
        with self._conn.cursor() as cur:
            cur.execute(f"SELECT seq, sub_seq, data FROM {cfg.live_table} "
                        f"WHERE session_id=%s ORDER BY seq, sub_seq", (sid,))
            rows = cur.fetchall()
        self._conn.commit()
        return dmss.rows_to_history(rows)

    def sync(self, sid: str) -> tuple:
        """Live rows -> archive, in one transaction. Returns the verified
        (rows, md5); raises if the two sides do not match afterwards."""
        self.ensure()
        conn = self._conn
        try:
            with conn.cursor() as cur:
                cur.execute(f"""DELETE FROM {cfg.archive_table} a WHERE a.session_id=%s AND NOT EXISTS (
                                  SELECT 1 FROM {cfg.live_table} l
                                  WHERE l.session_id=a.session_id AND l.seq=a.seq AND l.sub_seq=a.sub_seq)""",
                            (sid,))
                cur.execute(f"""INSERT INTO {cfg.archive_table}
                                  (session_id, seq, sub_seq, data, created_at, updated_at, archived_at)
                                SELECT session_id, seq, sub_seq, data, created_at, updated_at, NOW()
                                FROM {cfg.live_table} WHERE session_id=%s
                                ON CONFLICT (session_id, seq, sub_seq) DO UPDATE
                                SET data=EXCLUDED.data, created_at=EXCLUDED.created_at,
                                    updated_at=EXCLUDED.updated_at, archived_at=NOW()
                                WHERE {cfg.archive_table}.updated_at IS DISTINCT FROM EXCLUDED.updated_at
                                   OR {cfg.archive_table}.data IS DISTINCT FROM EXCLUDED.data""",
                            (sid,))
                live = self._fingerprint(cur, cfg.live_table, sid)
                arc = self._fingerprint(cur, cfg.archive_table, sid)
                if live != arc:
                    raise RuntimeError(f"archive copy does not match live rows ({live} vs {arc})")
                cur.execute(f"""INSERT INTO {cfg.ledger_table} (session_id, rows, content_md5, backed_up_at)
                                VALUES (%s, %s, %s, NOW())
                                ON CONFLICT (session_id) DO UPDATE
                                SET rows=EXCLUDED.rows, content_md5=EXCLUDED.content_md5,
                                    backed_up_at=NOW()""", (sid, live[0], live[1]))
            conn.commit()
            return live
        except Exception:
            conn.rollback()
            raise

    def delete_live(self, sid: str, expect: tuple, zip_name: str):
        """Delete the live rows only if they still match what was backed up."""
        self.ensure()
        conn = self._conn
        try:
            with conn.cursor() as cur:
                cur.execute(f"SELECT 1 FROM {cfg.live_table} WHERE session_id=%s FOR UPDATE", (sid,))
                now = self._fingerprint(cur, cfg.live_table, sid)
                if now != expect:
                    raise _Changed(f"live rows changed after the backup ({expect} -> {now})")
                cur.execute(f"DELETE FROM {cfg.live_table} WHERE session_id=%s", (sid,))
                cur.execute(f"UPDATE {cfg.ledger_table} SET purged_at=NOW(), zip_name=%s, "
                            f"restored_at=NULL WHERE session_id=%s", (zip_name, sid))
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def has_live(self, sid: str) -> bool:
        self.ensure()
        with self._conn.cursor() as cur:
            cur.execute(f"SELECT 1 FROM {cfg.live_table} WHERE session_id=%s LIMIT 1", (sid,))
            r = cur.fetchone() is not None
        self._conn.commit()
        return r

    def restore(self, sid: str, history: Optional[dict]) -> int:
        """Rows back into the live table: from the archive table when it has
        them (exact, timestamps kept), else from the history in the ZIP."""
        self.ensure()
        conn = self._conn
        try:
            with conn.cursor() as cur:
                cur.execute(f"DELETE FROM {cfg.live_table} WHERE session_id=%s", (sid,))
                cur.execute(f"""INSERT INTO {cfg.live_table} (session_id, seq, sub_seq, data, created_at, updated_at)
                                SELECT session_id, seq, sub_seq, data, created_at, updated_at
                                FROM {cfg.archive_table} WHERE session_id=%s""", (sid,))
                n = cur.rowcount
                if n <= 0 and history:
                    rows = [(sid, s, ss, dmss.row_json(v)) for s, ss, v in dmss.iter_rows(history)]
                    cur.executemany(f"""INSERT INTO {cfg.live_table} (session_id, seq, sub_seq, data)
                                        VALUES (%s, %s, %s, %s::jsonb)""", rows)
                    n = len(rows)
                cur.execute(f"UPDATE {cfg.ledger_table} SET restored_at=NOW(), purged_at=NULL "
                            f"WHERE session_id=%s", (sid,))
            conn.commit()
            return n
        except Exception:
            conn.rollback()
            raise


class _CosmosBackend:
    """Same contract as _PgBackend over two Cosmos containers. The archive
    container must exist beforehand with partition key /session_id.

    Not exercised in CI: no Cosmos account is configured here."""
    name = "cosmos"

    def __init__(self):
        self._live = None
        self._arc = None

    def close(self):
        pass

    def ensure(self):
        if self._live is not None:
            return
        from azure.cosmos import CosmosClient
        endpoint, key = os.getenv("COSMOS_ENDPOINT"), os.getenv("COSMOS_KEY")
        if not endpoint or not key:
            raise RuntimeError("COSMOS_ENDPOINT / COSMOS_KEY are required")
        db = CosmosClient(endpoint, credential=key).get_database_client(
            os.getenv("COSMOS_DATABASE") or _setting.get("COSMOS_DATABASE", "digimatsu"))
        self._live = db.get_container_client(
            os.getenv("COSMOS_CONTAINER") or _setting.get("COSMOS_CONTAINER", "chat_history"))
        self._arc = db.get_container_client(cfg.cosmos_archive_container)

    @staticmethod
    def _ts(epoch) -> Optional[datetime]:
        return datetime.fromtimestamp(int(epoch), tz=timezone.utc) if epoch else None

    def _stats(self, container) -> dict:
        out = {}
        for it in container.query_items(
                query="SELECT c.session_id, COUNT(1) AS n, MAX(c._ts) AS m FROM c GROUP BY c.session_id",
                enable_cross_partition_query=True):
            out[it["session_id"]] = (int(it["n"]), self._ts(it.get("m")))
        return out

    def live_stats(self) -> dict:
        self.ensure()
        return {k: (n, m, 0) for k, (n, m) in self._stats(self._live).items()}

    def archive_stats(self) -> dict:
        self.ensure()
        return self._stats(self._arc)

    def ledger(self) -> dict:
        return {}

    def _docs(self, container, sid: str) -> dict:
        return {(int(it["seq"]), int(it["sub_seq"])): it.get("data", {})
                for it in container.query_items(
                    query="SELECT c.seq, c.sub_seq, c.data FROM c WHERE c.session_id=@s",
                    parameters=[{"name": "@s", "value": sid}], partition_key=sid)}

    @staticmethod
    def _fp(docs: dict) -> tuple:
        h = hashlib.md5()
        for k in sorted(docs):
            h.update(hashlib.md5(dmss.row_json(docs[k]).encode("utf-8")).hexdigest().encode())
        return len(docs), h.hexdigest()

    def history(self, sid: str) -> dict:
        self.ensure()
        return dmss.rows_to_history((s, ss, d) for (s, ss), d in self._docs(self._live, sid).items())

    def sync(self, sid: str) -> tuple:
        self.ensure()
        live = self._docs(self._live, sid)
        arc = self._docs(self._arc, sid)
        for (s, ss), d in live.items():
            if arc.get((s, ss)) != d:
                self._arc.upsert_item({"id": f"{s}-{ss}", "session_id": sid, "seq": s,
                                       "sub_seq": ss, "data": d, "archived_at": _iso(_now())})
        for (s, ss) in set(arc) - set(live):
            self._arc.delete_item(item=f"{s}-{ss}", partition_key=sid)
        fp_live, fp_arc = self._fp(live), self._fp(self._docs(self._arc, sid))
        if fp_live != fp_arc:
            raise RuntimeError(f"archive copy does not match live docs ({fp_live} vs {fp_arc})")
        return fp_live

    def delete_live(self, sid: str, expect: tuple, zip_name: str):
        self.ensure()
        live = self._docs(self._live, sid)
        if self._fp(live) != expect:
            raise _Changed("live docs changed after the backup")
        for (s, ss) in live:
            self._live.delete_item(item=f"{s}-{ss}", partition_key=sid)

    def has_live(self, sid: str) -> bool:
        self.ensure()
        return bool(self._docs(self._live, sid))

    def restore(self, sid: str, history: Optional[dict]) -> int:
        self.ensure()
        docs = self._docs(self._arc, sid)
        if not docs and history:
            docs = {(s, ss): v for s, ss, v in dmss.iter_rows(history)}
        for (s, ss), d in docs.items():
            self._live.upsert_item({"id": f"{s}-{ss}", "session_id": sid, "seq": s,
                                    "sub_seq": ss, "data": d})
        return len(docs)


class _Changed(Exception):
    """The session was written to between the backup and the delete."""


def _db_backend():
    m = _store_method()
    if m == "PostgreSQL":
        return _PgBackend()
    if m == "CosmosDB":
        return _CosmosBackend()
    return None


def _forget(sid: str):
    try:
        st = dmss.get_store()
        if hasattr(st, "forget"):
            st.forget(sid)
    except Exception:
        pass


# ============================================================== scan ====
def _folder_files(folder: str) -> list:
    out = []
    for p in Path(folder).rglob("*"):
        if p.is_file():
            out.append(p)
    return out


def _mtime(path: str) -> Optional[datetime]:
    try:
        return datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc)
    except OSError:
        return None


def _last_conversation(status: dict) -> Optional[datetime]:
    """status.yaml `last_update_date`: when the session's last turn finished.
    Written as naive local time by the container clock."""
    v = status.get("last_update_date")
    if not v:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(str(v), fmt).astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def _read_status(folder: str) -> dict:
    p = os.path.join(folder, cfg.status_file)
    if not os.path.exists(p):
        return {}
    try:
        return dmu.read_yaml_file(p) or {}
    except Exception:
        return {}


def _session_ids_on_disk() -> list:
    out = []
    if not os.path.isdir(cfg.user_folder):
        return out
    for e in os.scandir(cfg.user_folder):
        if e.is_dir() and e.name.startswith(cfg.prefix):
            out.append(e.name[len(cfg.prefix):])
    return out


def scan(days: Optional[float] = None, exclude: Iterable[str] = (),
         session_ids: Optional[Iterable[str]] = None) -> list:
    """Every session with where it lives, how old it is and whether it is
    backed up. `eligible` is what a purge with `days` would take."""
    exclude = set(exclude or ())
    only = set(session_ids) if session_ids else None
    be = _db_backend()
    live, arc, ledger = {}, {}, {}
    db_ok = True
    if be is not None:
        try:
            live, arc, ledger = be.live_stats(), be.archive_stats(), be.ledger()
        except Exception as e:
            # Without the DB a folder with no chat_memory.json could be a DB
            # session as well as an empty one; guessing "empty" would let a
            # purge delete the folder of a session whose rows were never
            # backed up.
            db_ok = False
            logger.error("history archive: %s backend unavailable (%s)", be.name, e)
        finally:
            be.close()
    zipped = _zip_index()

    now = _now()
    ids = set(_session_ids_on_disk()) | set(live)
    if only is not None:
        ids &= only
    out = []
    for sid in sorted(ids):
        folder = cfg.folder(sid)
        has_folder = os.path.isdir(folder)
        status = _read_status(folder) if has_folder else {}
        hist_path = os.path.join(folder, cfg.history_file)
        size = 0
        if has_folder:
            size = sum(p.stat().st_size for p in _folder_files(folder))
        # Idle time is measured from the newer of the last turn
        # (last_update_date) and the last write to the history. The turn alone
        # misses a session the scheduler keeps pushing into (a push does not
        # move last_update_date), and status.yaml's own mtime is not activity
        # at all: export bookkeeping, locks, hiding and renames all rewrite it,
        # and a bulk touch in September made months-old sessions look 66 days
        # old.
        conv = _last_conversation(status)
        if os.path.exists(hist_path):
            backend = "file"
            wrote = _mtime(hist_path)
            rows = None
        elif sid in live:
            backend = be.name
            rows, wrote, db_size = live[sid]
            size += db_size
        elif not db_ok:
            backend = "unknown"
            rows = None
            wrote = None
        else:
            backend = "none"
            rows = 0
            wrote = None
        last = max(filter(None, [conv, wrote]), default=None)
        if last is None and backend == "none":
            # Neither a turn nor a history: the only clock left is the folder.
            last = _mtime(os.path.join(folder, cfg.status_file)) or _mtime(folder)
        age = (now - last).total_seconds() / 86400 if last else None

        if backend in ("postgres", "cosmos"):
            a = arc.get(sid)
            if a is None:
                backup = "none"
            elif a[0] == live[sid][0] and a[1] == live[sid][1]:
                backup = "current"
            else:
                backup = "stale"
        else:
            backup = "zip" if zipped.get(sid) else "-"

        locked = str(status.get("status", "")).upper() == "LOCKED"
        reason = ""
        if backend == "unknown":
            reason = "database unavailable"
        elif sid in exclude:
            reason = "excluded (open in this window)"
        elif locked:
            reason = "locked (a run is in progress)"
        elif days is not None and (age is None or age < float(days)):
            reason = f"newer than {days:g} days"
        out.append({
            "id": sid,
            "name": status.get("name", ""),
            "user_id": status.get("user_id", ""),
            "active": status.get("active", ""),
            "backend": backend,
            "has_folder": has_folder,
            "last_activity": _iso(last),
            "last_conversation": _iso(conv),
            "last_write": _iso(wrote),
            "age_days": round(age, 1) if age is not None else None,
            "rows": rows,
            "size": size,
            "locked": locked,
            "backup": backup,
            "zips": zipped.get(sid, []),
            "ledger": ledger.get(sid, {}),
            "eligible": days is not None and not reason,
            "reason": reason,
        })
    return out


# =============================================================== ZIPs ====
def _zip_path(name: str) -> str:
    return os.path.join(cfg.archive_folder, name)


def list_archives() -> list:
    """ZIPs in ARCHIVE_FOLDER, newest first, with the sessions each holds.
    ZIPs written before manifest.json existed are read from their names."""
    out = []
    if not os.path.isdir(cfg.archive_folder):
        return out
    for name in sorted((f for f in os.listdir(cfg.archive_folder) if f.endswith(".zip")), reverse=True):
        p = _zip_path(name)
        entry = {"zip": name, "size": os.path.getsize(p), "created_at": _iso(_mtime(p)),
                 "action": "", "sessions": {}}
        try:
            with zipfile.ZipFile(p) as zf:
                names = zf.namelist()
                if "manifest.json" in names:
                    man = json.loads(zf.read("manifest.json").decode("utf-8"))
                    entry.update(created_at=man.get("created_at", entry["created_at"]),
                                 action=man.get("action", ""), sessions=man.get("sessions", {}))
                else:
                    sids = {n.split("/", 1)[0][len(cfg.prefix):] for n in names
                            if n.startswith(cfg.prefix) and "/" in n}
                    entry["sessions"] = {s: {"backend": "file"} for s in sorted(sids)}
        except Exception as e:
            entry["error"] = str(e)
        out.append(entry)
    return out


def zip_sessions(zip_name: str) -> dict:
    """{session_id: manifest entry} for one ZIP, without opening the rest."""
    with zipfile.ZipFile(_zip_path(zip_name)) as zf:
        names = zf.namelist()
        if "manifest.json" in names:
            return json.loads(zf.read("manifest.json").decode("utf-8")).get("sessions", {})
        sids = {n.split("/", 1)[0][len(cfg.prefix):] for n in names
                if n.startswith(cfg.prefix) and "/" in n}
        return {sid: {"backend": "file"} for sid in sorted(sids)}


def _zip_index() -> dict:
    idx: dict = {}
    for a in list_archives():
        for sid in a.get("sessions", {}):
            idx.setdefault(sid, []).append(a["zip"])
    return idx


def _crc32(path: Path) -> int:
    import zlib
    crc = 0
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            crc = zlib.crc32(chunk, crc)
    return crc & 0xFFFFFFFF


def _write_zip(items: list, action: str) -> tuple:
    """Write every session in `items` to one new ZIP and verify it.

    `items`: [{"id", "backend", "history": dict|None, "info": scan row}].
    Returns (zip_name, {sid: snapshot}) where snapshot records the folder
    files as they were zipped, so the delete can tell a later change apart.
    Written to a temporary name first: a half-written ZIP must never show up
    in the download list or in the Performance Explorer.
    """
    os.makedirs(cfg.archive_folder, exist_ok=True)
    name = "sessions_archive_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".zip"
    while os.path.exists(_zip_path(name)):
        time.sleep(1)
        name = "sessions_archive_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".zip"
    tmp = _zip_path("." + name + ".part")
    manifest = {"format": _ZIP_FORMAT, "created_at": _iso(_now()), "action": action,
                "store": _store_method(), "sessions": {}}
    snapshots = {}
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            for it in items:
                sid = it["id"]
                folder = cfg.folder(sid)
                arc_root = f"{cfg.prefix}{sid}"
                files, snap = {}, {}
                if os.path.isdir(folder):
                    for p in _folder_files(folder):
                        rel = p.relative_to(folder).as_posix()
                        st = p.stat()
                        zf.write(p, f"{arc_root}/{rel}")
                        files[rel] = {"size": st.st_size, "crc": _crc32(p)}
                        snap[rel] = (st.st_size, st.st_mtime_ns)
                hist_sha = ""
                if it.get("history") is not None:
                    body = json.dumps(it["history"], ensure_ascii=False, indent=4).encode("utf-8")
                    zf.writestr(f"{arc_root}/{cfg.history_file}", body)
                    hist_sha = hashlib.sha256(body).hexdigest()
                info = it.get("info") or {}
                manifest["sessions"][sid] = {
                    "backend": it["backend"], "name": info.get("name", ""),
                    "user_id": info.get("user_id", ""), "last_activity": info.get("last_activity", ""),
                    "rows": info.get("rows"), "files": files, "history_sha256": hist_sha,
                }
                snapshots[sid] = snap
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        _verify_zip(tmp, manifest)
        os.replace(tmp, _zip_path(name))
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return name, snapshots


def _verify_zip(path: str, manifest: dict):
    with zipfile.ZipFile(path) as zf:
        bad = zf.testzip()
        if bad:
            raise RuntimeError(f"ZIP member failed its CRC check: {bad}")
        infos = {i.filename: i for i in zf.infolist()}
        for sid, m in manifest["sessions"].items():
            root = f"{cfg.prefix}{sid}"
            for rel, f in m["files"].items():
                i = infos.get(f"{root}/{rel}")
                if i is None or i.file_size != f["size"] or i.CRC != f["crc"]:
                    raise RuntimeError(f"ZIP does not hold {root}/{rel} as it is on disk")
            if m.get("history_sha256"):
                body = zf.read(f"{root}/{cfg.history_file}")
                if hashlib.sha256(body).hexdigest() != m["history_sha256"]:
                    raise RuntimeError(f"ZIP history for {sid} does not match what was written")


def _folder_unchanged(sid: str, snap: dict) -> bool:
    folder = cfg.folder(sid)
    if not os.path.isdir(folder):
        return not snap
    now = {}
    for p in _folder_files(folder):
        st = p.stat()
        now[p.relative_to(folder).as_posix()] = (st.st_size, st.st_mtime_ns)
    return now == snap


# ======================================================== cross-process lock
class _RunLock:
    """WebUI, scheduler, CLI and API can all start a run; two at once would
    zip and delete the same sessions. A lock file in ARCHIVE_FOLDER covers the
    processes, `_run_lock` the threads; a lock older than 6 h is treated as
    left behind by a crashed run."""
    STALE_SEC = 6 * 3600

    def __init__(self):
        self.path = os.path.join(cfg.archive_folder, ".history_archive.lock")
        self.fd = None

    def __enter__(self):
        if not _run_lock.acquire(blocking=False):
            raise RuntimeError("another history archive run is in progress")
        os.makedirs(cfg.archive_folder, exist_ok=True)
        for _ in range(2):
            try:
                self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self.fd, f"{os.getpid()} {_iso(_now())}".encode())
                return self
            except FileExistsError:
                if time.time() - os.path.getmtime(self.path) > self.STALE_SEC:
                    os.remove(self.path)
                    continue
                _run_lock.release()
                raise RuntimeError("another history archive run is in progress "
                                   f"(lock file {self.path})")
        _run_lock.release()
        raise RuntimeError("could not take the history archive lock")

    def __exit__(self, *exc):
        try:
            if self.fd is not None:
                os.close(self.fd)
            os.remove(self.path)
        except OSError:
            pass
        _run_lock.release()


# ===================================================== analytics export ==
def _export_first(sid: str) -> str:
    """Bring the session's rows in digim_sessions / dialogs / references in
    line with its whole history before the history disappears: the mirror
    is kept for analytics, and after the purge nothing can correct it.
    Returns "" when done or not applicable, else why the purge must wait."""
    try:
        import DigiM_DB_Export as dbex
    except Exception:
        return ""
    if not dbex.auto_export_enabled():
        return ""
    r = dbex.resync_session_safe(sid)
    if r.get("status") in ("ok", "empty"):
        return ""
    return f"analytics export failed: {r.get('error', r.get('status'))}"


# ===================================================== analytics archive ===
# digim_sessions / dialogs / references are copied into *_archive tables
# that nothing deletes from, so the mirror itself can be trimmed while the
# users, agents, inputs, outputs, references and vectors stay queryable.
#
# Rows are keyed by turn, not by the mirror's surrogate ids: a resync can
# give a turn's references new ids, and dialog_id on old rows was assigned
# by counting and pointed at neighbouring turns. A turn's references are
# numbered by their order in the mirror (ref_no), which assumes the mirror
# is trimmed by whole turns, never by single references.
_MIRROR_KEYS = {
    "digim_sessions": ("session_id",),
    "digim_dialogs": ("session_id", "seq", "sub_seq"),
    "digim_references": ("session_id", "seq", "sub_seq", "ref_no"),
    "digim_steps": ("session_id", "seq", "sub_seq", "step_no"),
}
_MIRROR_OMIT = {"digim_sessions": {"id"}, "digim_dialogs": {"id"},
                "digim_references": {"id", "dialog_id"}, "digim_steps": set()}
# The last key column numbers the rows of a turn. References have no such
# column in the mirror, so theirs is derived from the row order.
_MIRROR_ORDINAL = {"digim_references": "ref_no", "digim_steps": "step_no"}
# Created by the first export after an upgrade, so it may not exist yet.
_MIRROR_OPTIONAL = {"digim_steps"}
# Columns only the archive has, per mirror table.
_ARCHIVE_ONLY = {"digim_sessions": [("user_groups", "TEXT[]")]}
_MIRROR_INDEXES = {
    "digim_sessions": [("user_updated", "(user_id, last_update_date DESC)"),
                       ("agent_file", "(agent_file)")],
    "digim_dialogs": [("agent_resp_ts", "(agent_file, response_timestamp)"),
                      ("prompt_timestamp", "(prompt_timestamp)"),
                      ("model_name", "(model_name)")],
    "digim_references": [("rag_name_db_name", "(rag_name, db_name)"),
                         ("chunk_id", "(chunk_id)")],
    "digim_steps": [("kind_name", "(step_kind, step_name)"),
                    ("agent_file", "(agent_file)")],
}
# The mirror embeds these two columns into its vector columns.
_VECTOR_SOURCES = ("user_input", "response_text")


def _mirror_configured() -> bool:
    return bool(os.getenv("POSTGRES_HOST") and os.getenv("POSTGRES_DB"))


def _pg_columns(cur, table: str) -> list:
    cur.execute("SELECT a.attname, format_type(a.atttypid, a.atttypmod) FROM pg_attribute a "
                "WHERE a.attrelid = to_regclass(%s) AND a.attnum > 0 AND NOT a.attisdropped "
                "ORDER BY a.attnum", (table,))
    return cur.fetchall()


_indexed = set()


def _ensure_mirror_archive(cur) -> dict:
    """Create the archive tables, and add any column the mirror has gained
    since (persona_id arrived that way). Returns per mirror table the
    columns copied, with their types."""
    from psycopg2 import sql
    shared = {}
    for src, dst in cfg.mirror_archive.items():
        cols = [(n, t) for n, t in _pg_columns(cur, src) if n not in _MIRROR_OMIT[src]]
        if not cols:
            if src in _MIRROR_OPTIONAL:
                continue
            raise RuntimeError(f"analytics mirror table {src} not found")
        keys = _MIRROR_KEYS[src]
        extra = _ARCHIVE_ONLY.get(src, [])
        have = dict(_pg_columns(cur, dst))
        if not have:
            defs = [sql.SQL("{} {}").format(sql.Identifier(n), sql.SQL(t)) for n, t in cols + extra]
            if "ref_no" in keys:
                defs.append(sql.SQL("ref_no INTEGER NOT NULL"))
            defs.append(sql.SQL("archived_at TIMESTAMPTZ NOT NULL DEFAULT NOW()"))
            defs.append(sql.SQL("PRIMARY KEY ({})").format(sql.SQL(", ").join(map(sql.Identifier, keys))))
            cur.execute(sql.SQL("CREATE TABLE IF NOT EXISTS {} ({})").format(
                sql.Identifier(dst), sql.SQL(", ").join(defs)))
        else:
            for n, t in cols + extra:
                if n not in have:
                    cur.execute(sql.SQL("ALTER TABLE {} ADD COLUMN IF NOT EXISTS {} {}").format(
                        sql.Identifier(dst), sql.Identifier(n), sql.SQL(t)))
        # Every turn's export copies its session here now, and CREATE INDEX
        # takes a lock on the table even when the index is already there.
        if dst not in _indexed:
            for name, on in _MIRROR_INDEXES[src]:
                cur.execute(sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {} " + on).format(
                    sql.Identifier(f"{dst}_{name}_idx"), sql.Identifier(dst)))
            _indexed.add(dst)
        shared[src] = cols
    return shared


def _sync_mirror_table(cur, src: str, cols: list, session_ids) -> dict:
    """Upsert the mirror's rows into the archive copy; only rows that differ
    are written. A vector the mirror lost is kept while the text it was
    embedded from is unchanged, and dropped once the text changed."""
    from psycopg2 import sql
    dst = cfg.mirror_archive[src]
    D, I = sql.Identifier(dst), sql.Identifier
    keys = _MIRROR_KEYS[src]
    names = [n for n, _ in cols]
    vecs = [n for n, t in cols if t.startswith("vector")]
    plain = [n for n in names if n not in keys and n not in vecs]
    scope, args = sql.SQL(""), []
    if session_ids is not None:
        scope, args = sql.SQL(" WHERE s.session_id = ANY(%s)"), [list(session_ids)]

    targets = names + (["ref_no"] if "ref_no" in keys else [])
    picks = [sql.SQL("s.{}").format(I(n)) for n in names]
    if "ref_no" in keys:
        picks.append(sql.SQL("row_number() OVER (PARTITION BY s.session_id, s.seq, s.sub_seq ORDER BY s.id)"))
    text_same = sql.SQL(" AND ").join(
        [sql.SQL("{}.{} IS NOT DISTINCT FROM EXCLUDED.{}").format(D, I(n), I(n))
         for n in _VECTOR_SOURCES if n in names] or [sql.SQL("TRUE")])
    sets = [sql.SQL("{} = EXCLUDED.{}").format(I(n), I(n)) for n in plain]
    sets += [sql.SQL("{v} = CASE WHEN EXCLUDED.{v} IS NULL AND {same} THEN {d}.{v} ELSE EXCLUDED.{v} END")
             .format(v=I(v), same=text_same, d=D) for v in vecs]
    sets.append(sql.SQL("archived_at = NOW()"))
    differs = [sql.SQL("({}) IS DISTINCT FROM ({})").format(
        sql.SQL(", ").join(sql.SQL("{}.{}").format(D, I(n)) for n in plain),
        sql.SQL(", ").join(sql.SQL("EXCLUDED.{}").format(I(n)) for n in plain))] if plain else []
    differs += [sql.SQL("(EXCLUDED.{v} IS NOT NULL AND {d}.{v} IS DISTINCT FROM EXCLUDED.{v})")
                .format(v=I(v), d=D) for v in vecs]
    cur.execute(sql.SQL(
        "INSERT INTO {d} ({targets}) SELECT {picks} FROM {s} s{scope} "
        "ON CONFLICT ({keys}) DO UPDATE SET {sets} WHERE {differs} RETURNING (xmax = 0)").format(
            d=D, s=I(src), scope=scope,
            targets=sql.SQL(", ").join(map(I, targets)), picks=sql.SQL(", ").join(picks),
            keys=sql.SQL(", ").join(map(I, keys)), sets=sql.SQL(", ").join(sets),
            differs=sql.SQL(" OR ").join(differs or [sql.SQL("FALSE")])), args)
    flags = [r[0] for r in cur.fetchall()]
    out = {"added": sum(1 for f in flags if f), "updated": sum(1 for f in flags if not f)}

    if src in _MIRROR_ORDINAL:
        # A turn the mirror rewrote with fewer references or steps leaves
        # stale ones numbered past the end. A turn the mirror no longer
        # holds any for is left alone: that is a trimmed turn.
        cur.execute(sql.SQL(
            "DELETE FROM {d} a USING (SELECT s.session_id, s.seq, s.sub_seq, COUNT(*) AS n "
            "FROM {s} s{scope} GROUP BY 1, 2, 3) c "
            "WHERE a.session_id = c.session_id AND a.seq = c.seq AND a.sub_seq = c.sub_seq "
            "AND a.{o} > c.n").format(d=D, s=I(src), scope=scope, o=I(_MIRROR_ORDINAL[src])), args)
        out["removed"] = cur.rowcount
    if vecs:
        cur.execute(sql.SQL("SELECT COUNT(*) FILTER (WHERE {} IS NOT NULL), COUNT(*) FROM {}").format(I(vecs[0]), D))
        out["with_vectors"], out["rows"] = cur.fetchone()
    return out


def archive_mirror(session_ids: Optional[Iterable[str]] = None, dry_run: bool = False, conn=None) -> dict:
    """Copy the analytics mirror into digim_sessions_archive /
    digim_dialogs_archive / digim_references_archive / digim_steps_archive,
    and record each session's user groups. Every session unless
    `session_ids` is given. Nothing is removed from the archive except
    references past the end of a turn the mirror rewrote."""
    if conn is None and not _mirror_configured():
        return {"status": "unavailable"}
    import psycopg2
    own = conn is None
    if own:
        conn = psycopg2.connect(**dmss.pg_connect_kwargs())
        conn.autocommit = False
    cur = conn.cursor()
    try:
        cur.execute("SELECT to_regclass('digim_dialogs') IS NOT NULL")
        if not cur.fetchone()[0]:
            conn.rollback()
            return {"status": "no mirror"}
        shared = _ensure_mirror_archive(cur)
        out = {"status": "ok", "dry_run": dry_run}
        ids = None if session_ids is None else list(session_ids)
        for src in shared:
            out[cfg.mirror_archive[src]] = _sync_mirror_table(cur, src, shared[src], ids)
        out["groups_stamped"] = _stamp_user_groups(cur, ids)
        if dry_run:
            conn.rollback()
            _indexed.clear()
        else:
            conn.commit()
        return out
    except Exception:
        conn.rollback()
        # Whatever this transaction created is gone with it.
        _indexed.clear()
        raise
    finally:
        cur.close()
        if own:
            conn.close()


def _stamp_user_groups(cur, session_ids) -> int:
    """Record on each archived session the groups its user belongs to.

    The archive outlives the user master: once a user is removed there, the
    group could no longer be looked up. It is written once and then kept, so
    a user who changes group later does not move their old sessions.
    """
    import DigiM_MstStore as dmms
    from psycopg2 import sql
    users, groups = [], []
    for uid, info in (dmms.load("users") or {}).items():
        raw = info.get("Group", "") if isinstance(info, dict) else ""
        gs = [g for g in raw if g] if isinstance(raw, list) else ([raw] if raw else [])
        if gs:
            users.append(str(uid))
            groups.append(json.dumps(gs, ensure_ascii=False))
    if not users:
        return 0
    scope, args = sql.SQL(""), [users, groups]
    if session_ids is not None:
        scope = sql.SQL(" AND a.session_id = ANY(%s)")
        args.append(session_ids)
    cur.execute(sql.SQL(
        "UPDATE {d} a SET user_groups = ARRAY(SELECT jsonb_array_elements_text(m.g::jsonb)) "
        "FROM unnest(%s::text[], %s::text[]) AS m(user_id, g) "
        "WHERE a.user_id = m.user_id AND a.user_groups IS NULL{scope}").format(
            d=sql.Identifier(cfg.mirror_archive["digim_sessions"]), scope=scope), args)
    return cur.rowcount


def _archive_mirror_into(report: dict, session_ids, dry_run: bool = False) -> bool:
    try:
        report["mirror"] = archive_mirror(session_ids, dry_run=dry_run)
        return True
    except Exception as e:
        report["errors"].append({"id": "(analytics archive)", "error": str(e)})
        return False


def _mirror_summary(m: Optional[dict]) -> str:
    """One line for logs and the WebUI."""
    if not m or m.get("status") != "ok":
        return (m or {}).get("status", "")
    parts = []
    for label, key in (("sessions", "digim_sessions_archive"), ("dialogs", "digim_dialogs_archive"),
                       ("references", "digim_references_archive"), ("steps", "digim_steps_archive")):
        t = m.get(key)
        if t is not None:
            parts.append(f"{label} +{t.get('added', 0)}/~{t.get('updated', 0)}")
    return ", ".join(parts)


# ================================================================ backup ===
def backup(days: Optional[float] = None, session_ids: Optional[Iterable[str]] = None,
           exclude: Iterable[str] = (), dry_run: bool = False) -> dict:
    """DB sessions whose live rows changed are copied to the archive store,
    and the analytics mirror to its archive tables. With `days`, sessions
    idle that long are also written to a ZIP (the only backup a file session
    gets). Nothing is deleted."""
    report = {"action": "backup", "dry_run": dry_run, "days": days, "zip": None,
              "synced": [], "zipped": [], "skipped": [], "mirror": None, "errors": []}
    rows = scan(days=days, exclude=exclude, session_ids=session_ids)
    db_rows = [r for r in rows if r["backend"] in ("postgres", "cosmos")]
    to_sync = [r for r in db_rows if r["backup"] != "current"]
    to_zip = [r for r in rows if days is not None and r["eligible"]]
    if dry_run:
        report["synced"] = [r["id"] for r in to_sync]
        report["zipped"] = [r["id"] for r in to_zip]
        _archive_mirror_into(report, session_ids, dry_run=True)
        return report
    with _RunLock():
        be = _db_backend()
        try:
            for r in to_sync:
                try:
                    be.sync(r["id"])
                    report["synced"].append(r["id"])
                except Exception as e:
                    report["errors"].append({"id": r["id"], "error": str(e)})
            items = []
            for r in to_zip:
                hist = None
                if r["backend"] in ("postgres", "cosmos"):
                    try:
                        hist = be.history(r["id"])
                    except Exception as e:
                        report["errors"].append({"id": r["id"], "error": str(e)})
                        continue
                items.append({"id": r["id"], "backend": r["backend"], "history": hist, "info": r})
            if items:
                report["zip"], _ = _write_zip(items, "backup")
                report["zipped"] = [i["id"] for i in items]
            _archive_mirror_into(report, session_ids)
        finally:
            if be is not None:
                be.close()
    logger.info("history backup: synced=%d zipped=%d errors=%d zip=%s mirror=%s",
                len(report["synced"]), len(report["zipped"]), len(report["errors"]), report["zip"],
                _mirror_summary(report["mirror"]))
    return report


# ================================================================= purge ===
def purge(days: float, session_ids: Optional[Iterable[str]] = None,
          exclude: Iterable[str] = (), dry_run: bool = False) -> dict:
    """Back up, ZIP, verify and then delete every session idle for `days`."""
    if days is None:
        raise ValueError("purge needs days (how long a session must be idle)")
    report = {"action": "purge", "dry_run": dry_run, "days": days, "zip": None,
              "purged": [], "skipped": [], "mirror": None, "errors": []}
    rows = scan(days=days, exclude=exclude, session_ids=session_ids)
    # "newer than N days" is most sessions on every run, so it is only worth
    # reporting when the caller named the sessions.
    report["skipped"] = [{"id": r["id"], "reason": r["reason"]} for r in rows
                         if not r["eligible"] and r["reason"]
                         and (session_ids or not r["reason"].startswith("newer than"))]
    cands = [r for r in rows if r["eligible"]]
    if dry_run:
        report["purged"] = [r["id"] for r in cands]
        return report
    if not cands:
        return report

    with _RunLock():
        be = _db_backend()
        try:
            ready = []
            for r in cands:
                sid = r["id"]
                why = _export_first(sid) if r["backend"] != "none" else ""
                if why:
                    report["skipped"].append({"id": sid, "reason": why})
                    continue
                item = {"id": sid, "backend": r["backend"], "history": None, "info": r}
                if r["backend"] in ("postgres", "cosmos"):
                    try:
                        item["fingerprint"] = be.sync(sid)
                        item["history"] = be.history(sid)
                    except Exception as e:
                        report["errors"].append({"id": sid, "error": f"backup failed: {e}"})
                        continue
                ready.append(item)
            if not ready:
                return report
            # The archive copy is what still holds these turns once the
            # mirror is trimmed, so it has to have them before anything goes.
            if not _archive_mirror_into(report, [i["id"] for i in ready]):
                return report

            # Nothing is deleted unless the whole ZIP was written and verified.
            report["zip"], snaps = _write_zip(ready, "purge")

            for item in ready:
                sid = item["id"]
                folder = cfg.folder(sid)
                aside = os.path.join(cfg.user_folder, f".purging_{sid}")
                moved = False
                try:
                    if not _folder_unchanged(sid, snaps.get(sid, {})):
                        raise _Changed("session folder changed after it was zipped")
                    # Out of the way first, so the delete can be undone if the
                    # history delete below refuses.
                    if os.path.isdir(folder):
                        os.replace(folder, aside)
                        moved = True
                    if item["backend"] in ("postgres", "cosmos"):
                        be.delete_live(sid, item["fingerprint"], report["zip"])
                        _forget(sid)
                except _Changed as e:
                    if moved:
                        os.replace(aside, folder)
                    report["skipped"].append({"id": sid, "reason": str(e)})
                    continue
                except Exception as e:
                    if moved:
                        os.replace(aside, folder)
                    report["errors"].append({"id": sid, "error": str(e)})
                    continue
                if moved:
                    shutil.rmtree(aside, ignore_errors=True)
                report["purged"].append(sid)
        finally:
            if be is not None:
                be.close()
    logger.info("history purge: purged=%d skipped=%d errors=%d zip=%s",
                len(report["purged"]), len(report["skipped"]), len(report["errors"]), report["zip"])
    return report


# =============================================================== restore ===
def restore(session_id: str, zip_name: Optional[str] = None, overwrite: bool = False) -> dict:
    """Bring a purged session back. The folder comes from the ZIP (the newest
    one holding the session unless `zip_name` says otherwise); DB rows come
    from the archive store, or from the ZIP's history when the store has none.
    A session that still exists is refused unless `overwrite`."""
    sid = session_id
    folder = cfg.folder(sid)
    if not zip_name:
        holding = [a["zip"] for a in list_archives() if sid in a.get("sessions", {})]
        if not holding:
            raise FileNotFoundError(f"no archive ZIP holds session {sid}")
        zip_name = holding[0]
    path = _zip_path(zip_name)
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        manifest = json.loads(zf.read("manifest.json").decode("utf-8")) if "manifest.json" in names else {}
        meta = (manifest.get("sessions") or {}).get(sid) or {"backend": "file"}
        root = f"{cfg.prefix}{sid}/"
        members = [n for n in names if n.startswith(root) and not n.endswith("/")]
        if not members and sid not in (manifest.get("sessions") or {}):
            raise FileNotFoundError(f"{zip_name} does not hold session {sid}")
        backend = meta.get("backend", "file")
        hist_member = root + cfg.history_file
        history = (json.loads(zf.read(hist_member).decode("utf-8"))
                   if hist_member in names else None)

        with _RunLock():
            # A DB-archived session restored where SESSION_STORE_METHOD is now
            # JSON comes back as a file session: the ZIP's chat_memory.json is
            # the whole history, so nothing is lost.
            be = _db_backend() if backend in ("postgres", "cosmos") else None
            try:
                exists = os.path.isdir(folder) or (be is not None and be.has_live(sid))
                if exists and not overwrite:
                    raise FileExistsError(f"session {sid} still exists; pass overwrite to replace it")
                # A DB session's history goes back into the DB. Left on disk as
                # chat_memory.json it would win over the rows (the hybrid read
                # prefers the file) and shadow them.
                to_extract = [n for n in members if not (be is not None and n == hist_member)]
                if os.path.isdir(folder):
                    shutil.rmtree(folder)
                for n in to_extract:
                    target = Path(folder) / n[len(root):]
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(n) as src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                rows = be.restore(sid, history) if be is not None else None
                _forget(sid)
            finally:
                if be is not None:
                    be.close()
    logger.info("history restore: %s from %s (%s)", sid, zip_name, backend)
    return {"action": "restore", "id": sid, "zip": zip_name, "backend": backend,
            "restored_as": "db" if be is not None else "file",
            "files": len(to_extract), "rows": rows}


# =================================================================== CLI ===
def _print_scan(rows: list):
    print(f"{'session':<24}{'backend':<9}{'age(d)':>7}{'rows':>6}{'size':>10}  {'backup':<8} {'eligible':<9} reason / name")
    for r in rows:
        size = f"{r['size'] / 1e6:.1f}MB" if r["size"] >= 1e5 else f"{r['size'] // 1024}KB"
        print(f"{r['id']:<24}{r['backend']:<9}{(r['age_days'] if r['age_days'] is not None else '-'):>7}"
              f"{(r['rows'] if r['rows'] is not None else '-'):>6}{size:>10}  {r['backup']:<8} "
              f"{'yes' if r['eligible'] else '':<9} {r['reason'] or r['name']}")


def _cli(argv) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="DigiM_HistoryArchive.py",
                                 description="Back up, purge and restore chat history.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for c in ("list", "backup", "purge"):
        p = sub.add_parser(c)
        p.add_argument("--days", type=float, default=None,
                       help=f"idle days (purge needs this or --session; default for list: "
                            f"ARCHIVE_DAYS={cfg.default_days})")
        p.add_argument("--session", action="append", default=None, help="limit to these session ids")
        if c != "list":
            p.add_argument("--dry-run", action="store_true", help="show what would happen")
    p = sub.add_parser("restore")
    p.add_argument("--session", required=True)
    p.add_argument("--zip", default=None)
    p.add_argument("--overwrite", action="store_true")
    sub.add_parser("archives")
    a = ap.parse_args(argv[1:])

    if a.cmd == "list":
        _print_scan(scan(days=a.days if a.days is not None else cfg.default_days, session_ids=a.session))
    elif a.cmd == "backup":
        print(json.dumps(backup(days=a.days, session_ids=a.session, dry_run=a.dry_run),
                         ensure_ascii=False, indent=2))
    elif a.cmd == "purge":
        if a.days is None and not a.session:
            print("purge needs --days (or --session with --days 0)", file=sys.stderr)
            return 2
        print(json.dumps(purge(days=a.days if a.days is not None else 0, session_ids=a.session,
                               dry_run=a.dry_run), ensure_ascii=False, indent=2))
    elif a.cmd == "restore":
        print(json.dumps(restore(a.session, zip_name=a.zip, overwrite=a.overwrite),
                         ensure_ascii=False, indent=2))
    elif a.cmd == "archives":
        for z in list_archives():
            print(f"{z['zip']}  {z['size'] / 1e6:.1f}MB  {z.get('action') or '(legacy)'}  "
                  f"{len(z.get('sessions', {}))} sessions")
    return 0


if __name__ == "__main__":
    dmu.setup_logging()
    sys.exit(_cli(sys.argv))
