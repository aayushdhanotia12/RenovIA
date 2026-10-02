"""SQLite storage for the prototype. Every project read is scoped by owner.

The owner is the anonymous browser identity (a random cookie) until accounts exist.
No query in this module returns a project, photo, design or job without matching
its owner, so one customer can never load another's room.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY, owner TEXT NOT NULL, created_at REAL NOT NULL,
  room_type TEXT NOT NULL DEFAULT 'kitchen',
  measurements TEXT, surfaces TEXT, description TEXT, suggestions TEXT, style_board TEXT
);
CREATE INDEX IF NOT EXISTS projects_owner ON projects(owner);
CREATE TABLE IF NOT EXISTS photos (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
  path TEXT NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL,
  checks TEXT, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
  kind TEXT NOT NULL, status TEXT NOT NULL, created_at REAL NOT NULL,
  finished_at REAL, result TEXT, error TEXT
);
CREATE TABLE IF NOT EXISTS designs (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), photo_id TEXT NOT NULL,
  choice TEXT NOT NULL, render_path TEXT NOT NULL, manifest TEXT NOT NULL, quote TEXT NOT NULL,
  model_versions TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS bookings (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), design_id TEXT,
  name TEXT NOT NULL, phone TEXT NOT NULL, address TEXT NOT NULL, preferred_window TEXT,
  fulfilment_type TEXT NOT NULL, notes TEXT, status TEXT NOT NULL DEFAULT 'new', created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS shares (
  id TEXT PRIMARY KEY, design_id TEXT NOT NULL REFERENCES designs(id), created_at REAL NOT NULL
);
"""

# Columns added after the first prototype: (table, column, type). Old databases get them on start.
MIGRATIONS = [
    ("projects", "style_board", "TEXT"),
    ("bookings", "scheduled_at", "TEXT"),      # local date-time the team agreed with the customer
    ("bookings", "assigned_to", "TEXT"),       # who from the field team goes
    ("bookings", "staff_notes", "TEXT"),
    ("bookings", "visited_at", "REAL"),
    ("bookings", "verified", "TEXT"),          # the team's measurements, JSON (integer mm)
    ("bookings", "final_quote", "TEXT"),       # quote re-priced from them, JSON
    ("bookings", "updated_at", "REAL"),
]
BOOKING_STATUSES = ("new", "scheduled", "visited", "cancelled")
BOOKING_EDITABLE = ("status", "scheduled_at", "assigned_to", "staff_notes")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:20]}"


class NotFound(LookupError):
    pass


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(SCHEMA)
            for table, column, kind in MIGRATIONS:
                cols = {r[1] for r in self._conn.execute(f"PRAGMA table_info({table})")}
                if column not in cols:
                    self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
            self._conn.commit()

    def _exec(self, sql: str, args: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, args)
            self._conn.commit()
            return cur

    def _one(self, sql: str, args: tuple = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, args).fetchone()

    def _all(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, args).fetchall()

    # projects --------------------------------------------------------------
    def create_project(self, owner: str) -> dict:
        pid = new_id("prj")
        self._exec("INSERT INTO projects (id, owner, created_at) VALUES (?, ?, ?)", (pid, owner, time.time()))
        return self.project(owner, pid)

    def project(self, owner: str, pid: str) -> dict:
        row = self._one("SELECT * FROM projects WHERE id = ? AND owner = ?", (pid, owner))
        if row is None:
            raise NotFound("project")
        out = dict(row)
        for key in ("measurements", "surfaces", "description", "suggestions", "style_board"):
            out[key] = json.loads(out[key]) if out[key] else None
        out["photos"] = [self._photo_row(r) for r in
                         self._all("SELECT * FROM photos WHERE project_id = ? ORDER BY created_at", (pid,))]
        out["designs"] = [
            {"id": r["id"], "photo_id": r["photo_id"], "choice": json.loads(r["choice"]), "created_at": r["created_at"]}
            for r in self._all("SELECT id, photo_id, choice, created_at FROM designs WHERE project_id = ? ORDER BY created_at",
                               (pid,))
        ]
        return out

    def update_project(self, owner: str, pid: str, **fields: Any) -> None:
        self.project(owner, pid)  # ownership check
        for key, value in fields.items():
            if key not in {"measurements", "surfaces", "description", "suggestions", "style_board", "room_type"}:
                raise KeyError(key)
            stored = json.dumps(value) if key != "room_type" else value
            self._exec(f"UPDATE projects SET {key} = ? WHERE id = ? AND owner = ?", (stored, pid, owner))

    # photos ----------------------------------------------------------------
    @staticmethod
    def _photo_row(r: sqlite3.Row) -> dict:
        d = dict(r)
        d["checks"] = json.loads(d["checks"]) if d["checks"] else None
        return d

    def add_photo(self, owner: str, pid: str, photo_id: str, path: str, width: int, height: int, checks: dict) -> dict:
        self.project(owner, pid)
        self._exec("INSERT INTO photos (id, project_id, path, width, height, checks, created_at) VALUES (?,?,?,?,?,?,?)",
                   (photo_id, pid, path, width, height, json.dumps(checks), time.time()))
        return self.photo(owner, pid, photo_id)

    def photo(self, owner: str, pid: str, photo_id: str) -> dict:
        row = self._one(
            "SELECT ph.* FROM photos ph JOIN projects p ON p.id = ph.project_id "
            "WHERE ph.id = ? AND ph.project_id = ? AND p.owner = ?", (photo_id, pid, owner))
        if row is None:
            raise NotFound("photo")
        return self._photo_row(row)

    # jobs ------------------------------------------------------------------
    def create_job(self, owner: str, pid: str, kind: str) -> str:
        self.project(owner, pid)
        jid = new_id("job")
        self._exec("INSERT INTO jobs (id, project_id, kind, status, created_at) VALUES (?,?,?,?,?)",
                   (jid, pid, kind, "running", time.time()))
        return jid

    def finish_job(self, jid: str, status: str, result: Any = None, error: str | None = None) -> None:
        self._exec("UPDATE jobs SET status = ?, finished_at = ?, result = ?, error = ? WHERE id = ?",
                   (status, time.time(), json.dumps(result) if result is not None else None, error, jid))

    def job(self, owner: str, jid: str) -> dict:
        row = self._one("SELECT j.* FROM jobs j JOIN projects p ON p.id = j.project_id WHERE j.id = ? AND p.owner = ?",
                        (jid, owner))
        if row is None:
            raise NotFound("job")
        d = dict(row)
        d["result"] = json.loads(d["result"]) if d["result"] else None
        return d

    # designs ---------------------------------------------------------------
    def add_design(self, pid: str, design_id: str, photo_id: str, choice: dict, render_path: str,
                   manifest: dict, quote: dict, model_versions: dict) -> None:
        self._exec(
            "INSERT INTO designs (id, project_id, photo_id, choice, render_path, manifest, quote, model_versions, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (design_id, pid, photo_id, json.dumps(choice), render_path, json.dumps(manifest), json.dumps(quote),
             json.dumps(model_versions), time.time()))

    def design(self, owner: str, design_id: str) -> dict:
        row = self._one("SELECT d.* FROM designs d JOIN projects p ON p.id = d.project_id WHERE d.id = ? AND p.owner = ?",
                        (design_id, owner))
        if row is None:
            raise NotFound("design")
        d = dict(row)
        for key in ("choice", "manifest", "quote", "model_versions"):
            d[key] = json.loads(d[key])
        return d

    # bookings --------------------------------------------------------------
    def add_booking(self, owner: str, pid: str, booking: dict) -> dict:
        self.project(owner, pid)
        bid = new_id("bkg")
        self._exec(
            "INSERT INTO bookings (id, project_id, design_id, name, phone, address, preferred_window, fulfilment_type,"
            " notes, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (bid, pid, booking.get("design_id"), booking["name"], booking["phone"], booking["address"],
             booking.get("preferred_window"), booking["fulfilment_type"], booking.get("notes"), time.time()))
        return {"id": bid, "status": "new"}

    # staff (every method below crosses customers: callers must check the staff token first)
    @staticmethod
    def _booking_row(r: sqlite3.Row) -> dict:
        d = dict(r)
        for key in ("quote", "verified", "final_quote", "choice"):
            if key in d:
                d[key] = json.loads(d[key]) if d[key] else None
        return d

    def staff_bookings(self) -> list[dict]:
        return [self._booking_row(r) for r in self._all(
            "SELECT b.*, d.quote AS quote, d.choice AS choice, d.photo_id AS photo_id FROM bookings b "
            "LEFT JOIN designs d ON d.id = b.design_id ORDER BY b.created_at DESC")]

    def staff_booking(self, bid: str) -> dict:
        row = self._one(
            "SELECT b.*, d.quote AS quote, d.choice AS choice, d.photo_id AS photo_id FROM bookings b "
            "LEFT JOIN designs d ON d.id = b.design_id WHERE b.id = ?", (bid,))
        if row is None:
            raise NotFound("booking")
        return self._booking_row(row)

    def staff_design(self, design_id: str) -> dict:
        row = self._one("SELECT * FROM designs WHERE id = ?", (design_id,))
        if row is None:
            raise NotFound("design")
        d = dict(row)
        for key in ("choice", "manifest", "quote", "model_versions"):
            d[key] = json.loads(d[key])
        return d

    def staff_project(self, pid: str) -> dict:
        row = self._one("SELECT owner FROM projects WHERE id = ?", (pid,))
        if row is None:
            raise NotFound("project")
        return self.project(row["owner"], pid)

    def update_booking(self, bid: str, **fields: Any) -> dict:
        self.staff_booking(bid)
        for key, value in fields.items():
            if key not in BOOKING_EDITABLE + ("visited_at", "verified", "final_quote"):
                raise KeyError(key)
            stored = json.dumps(value) if key in ("verified", "final_quote") and value is not None else value
            self._exec(f"UPDATE bookings SET {key} = ?, updated_at = ? WHERE id = ?", (stored, time.time(), bid))
        return self.staff_booking(bid)

    # shares: a read-only link to one design, made by its owner -----------------------
    def create_share(self, owner: str, design_id: str) -> str:
        self.design(owner, design_id)  # only the owner can share a design
        row = self._one("SELECT id FROM shares WHERE design_id = ?", (design_id,))
        if row is not None:
            return row["id"]
        sid = uuid.uuid4().hex + uuid.uuid4().hex[:8]
        self._exec("INSERT INTO shares (id, design_id, created_at) VALUES (?, ?, ?)", (sid, design_id, time.time()))
        return sid

    def shared_design(self, sid: str) -> dict:
        row = self._one("SELECT design_id FROM shares WHERE id = ?", (sid,))
        if row is None:
            raise NotFound("share")
        return self.staff_design(row["design_id"])
