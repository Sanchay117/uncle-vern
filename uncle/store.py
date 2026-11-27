"""Uncle's memory: one SQLite file on the Sprite's disk."""
import json
import os
import sqlite3
import threading
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages(
  message_id TEXT PRIMARY KEY,
  am_thread_id TEXT,
  sender TEXT,
  kind TEXT,            -- intake, owner_command, scammer, stranger, ignored, self
  status TEXT,          -- processing, done, error
  thread_ref INTEGER,
  detail TEXT,
  created_at REAL
);
CREATE TABLE IF NOT EXISTS threads(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  scammer_addr TEXT,
  scammer_name TEXT,
  scam_subject TEXT,
  scam_text TEXT,
  scam_type TEXT,
  scam_prob REAL,
  status TEXT,          -- pending_approval, declined, active, closed, rejected
  close_reason TEXT,
  owner_thread_id TEXT,
  owner_message_id TEXT,
  origin_message_id TEXT,
  am_thread_id TEXT,
  draft TEXT,
  created_at REAL,
  approved_at REAL,
  first_bite_at REAL,
  last_scammer_at REAL,
  hidden INTEGER DEFAULT 0,
  frustration REAL,
  asking_for TEXT,
  hooked REAL
);
CREATE TABLE IF NOT EXISTS letters(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  thread_id INTEGER,
  direction TEXT,       -- uncle, scammer
  message_id TEXT,
  body TEXT,            -- private, never served
  public_body TEXT,     -- redacted, served on the page
  words INTEGER,
  sent_at REAL,
  jev TEXT
);
CREATE TABLE IF NOT EXISTS boots(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at REAL,
  last_seen REAL,
  cpu_start REAL,
  cpu_last REAL,
  mem_sum REAL DEFAULT 0,
  mem_samples INTEGER DEFAULT 0,
  disk_gb REAL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS tries(id INTEGER PRIMARY KEY AUTOINCREMENT, ip_hash TEXT, at REAL);
CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS web_checks(id INTEGER PRIMARY KEY AUTOINCREMENT, phrase TEXT, at REAL, result TEXT);
CREATE TABLE IF NOT EXISTS practice(  -- someone who forwarded a scam, now playing the scammer by email
  am_thread_id TEXT PRIMARY KEY,
  visitor TEXT,
  scam TEXT,
  turns TEXT,           -- JSON [{who, text}], private, never served
  started_at REAL,
  updated_at REAL
);
CREATE TABLE IF NOT EXISTS diary(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at REAL,
  thread_id INTEGER,
  kind TEXT,
  text TEXT,
  public INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS letters_thread ON letters(thread_id);
CREATE INDEX IF NOT EXISTS threads_am ON threads(am_thread_id);
CREATE INDEX IF NOT EXISTS threads_owner ON threads(owner_thread_id);
"""


STALE = 900  # seconds before a message left "processing" counts as cut off


class Store:
    def __init__(self, path):
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.lock = threading.RLock()
        with self.lock:
            self.db.executescript(SCHEMA)
            # Columns added after the first deploy: a disk made by an older Uncle gets them here.
            have = {r["name"] for r in self.db.execute("PRAGMA table_info(threads)").fetchall()}
            for col, kind in (("kin", "TEXT"), ("vec", "TEXT"), ("flags", "TEXT"), ("web", "TEXT"),
                              ("send_after", "REAL"), ("title", "TEXT")):
                if col not in have:
                    self.db.execute(f"ALTER TABLE threads ADD COLUMN {col} {kind}")
            if "vec" not in have:
                # Kin worked out with the old reranker gets redone with embeddings on the next rounds.
                self.db.execute("UPDATE threads SET kin=NULL")

    # -- generic helpers
    def q(self, sql, args=()):
        with self.lock:
            return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    def one(self, sql, args=()):
        rows = self.q(sql, args)
        return rows[0] if rows else None

    def run(self, sql, args=()):
        with self.lock:
            cur = self.db.execute(sql, args)
            return cur.lastrowid

    # -- small facts Uncle keeps between wake-ups
    def get(self, key, default=None):
        r = self.one("SELECT value FROM state WHERE key=?", (key,))
        return r["value"] if r else default

    def put(self, key, value):
        self.run("INSERT OR REPLACE INTO state(key, value) VALUES(?,?)", (key, str(value)))

    # -- messages (dedupe and audit)
    def claim_message(self, message_id, am_thread_id, sender):
        """Returns False if this message was already handled or is being handled."""
        with self.lock:
            row = self.db.execute("SELECT status, created_at FROM messages WHERE message_id=?",
                                  (message_id,)).fetchone()
            # A message stuck "processing" for a quarter hour was cut off (a restart, say): try it again.
            if row and (row["status"] == "done" or (row["status"] == "processing"
                                                     and (row["created_at"] or 0) > time.time() - STALE)):
                return False
            self.db.execute(
                "INSERT OR REPLACE INTO messages(message_id, am_thread_id, sender, kind, status, created_at)"
                " VALUES(?,?,?,?,?,?)", (message_id, am_thread_id, sender, None, "processing", time.time()))
            return True

    def finish_message(self, message_id, kind, status="done", thread_ref=None, detail=None):
        self.run("UPDATE messages SET kind=?, status=?, thread_ref=?, detail=? WHERE message_id=?",
                 (kind, status, thread_ref, detail, message_id))

    def known_message(self, message_id):
        return self.one("SELECT * FROM messages WHERE message_id=?", (message_id,))

    # -- threads
    def new_thread(self, **f):
        f.setdefault("created_at", time.time())
        cols = ",".join(f)
        marks = ",".join("?" for _ in f)
        return self.run(f"INSERT INTO threads({cols}) VALUES({marks})", tuple(f.values()))

    def update_thread(self, tid, **f):
        sets = ",".join(f"{k}=?" for k in f)
        self.run(f"UPDATE threads SET {sets} WHERE id=?", (*f.values(), tid))

    def thread(self, tid):
        return self.one("SELECT * FROM threads WHERE id=?", (tid,))

    def thread_by_am(self, am_thread_id):
        return self.one("SELECT * FROM threads WHERE am_thread_id=?", (am_thread_id,))

    def active_by_scammer(self, addr):
        if not addr:
            return None
        return self.one("SELECT * FROM threads WHERE status='active' AND lower(scammer_addr)=? "
                        "ORDER BY id DESC LIMIT 1", (addr.lower(),))

    def pending_by_owner_thread(self, owner_thread_id):
        return self.one("SELECT * FROM threads WHERE owner_thread_id=? ORDER BY id DESC LIMIT 1",
                        (owner_thread_id,))

    def active_threads(self):
        return self.q("SELECT * FROM threads WHERE status='active'")

    def public_threads(self):
        return self.q("SELECT * FROM threads WHERE status IN ('active','closed') AND hidden=0 "
                      "AND approved_at IS NOT NULL ORDER BY COALESCE(last_scammer_at, approved_at) DESC")

    # -- letters
    def add_letter(self, thread_id, direction, message_id, body, public_body, jev=None, sent_at=None):
        if message_id:
            seen = self.one("SELECT id FROM letters WHERE message_id=?", (message_id,))
            if seen:
                return seen["id"]
        words = len(body.split())
        return self.run(
            "INSERT INTO letters(thread_id, direction, message_id, body, public_body, words, sent_at, jev)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (thread_id, direction, message_id, body, public_body, words, sent_at or time.time(),
             json.dumps(jev) if jev is not None else None))

    def letters(self, thread_id):
        return self.q("SELECT * FROM letters WHERE thread_id=? ORDER BY sent_at, id", (thread_id,))

    def uncle_letters_since(self, since, thread_id=None):
        if thread_id is None:
            r = self.one("SELECT COUNT(*) n FROM letters WHERE direction='uncle' AND sent_at>=?", (since,))
        else:
            r = self.one("SELECT COUNT(*) n FROM letters WHERE direction='uncle' AND sent_at>=? AND thread_id=?",
                         (since, thread_id))
        return r["n"]

    # -- diary: Uncle explains each thing he does
    def note(self, text, thread_id=None, kind="note", public=True):
        self.run("INSERT INTO diary(at, thread_id, kind, text, public) VALUES(?,?,?,?,?)",
                 (time.time(), thread_id, kind, text, 1 if public else 0))

    def diary(self, limit=30, thread_id=None):
        if thread_id is None:
            return self.q("SELECT * FROM diary WHERE public=1 ORDER BY id DESC LIMIT ?", (limit,))
        return self.q("SELECT * FROM diary WHERE public=1 AND thread_id=? ORDER BY id DESC LIMIT ?",
                      (thread_id, limit))

    # -- totals for the page
    def totals(self):
        t = self.one(
            "SELECT "
            " (SELECT COUNT(*) FROM threads WHERE approved_at IS NOT NULL) AS approached,"
            " (SELECT COUNT(*) FROM threads WHERE first_bite_at IS NOT NULL) AS bit,"
            " (SELECT COUNT(*) FROM threads WHERE close_reason LIKE '%bounced%') AS bounced,"
            " (SELECT COUNT(*) FROM letters WHERE direction='scammer') AS scammer_letters,"
            " (SELECT COALESCE(SUM(words),0) FROM letters WHERE direction='scammer') AS scammer_words,"
            " (SELECT COUNT(*) FROM letters WHERE direction='uncle') AS uncle_letters,"
            " (SELECT COALESCE(SUM(words),0) FROM letters WHERE direction='uncle') AS uncle_words,"
            # Uncle's words in conversations where the scammer wrote back, so we know they were read.
            " (SELECT COALESCE(SUM(l.words),0) FROM letters l JOIN threads t ON t.id=l.thread_id"
            "   WHERE l.direction='uncle' AND t.first_bite_at IS NOT NULL) AS uncle_words_read")
        # On the hook: from Uncle's first letter to the scammer's latest reply.
        longest = self.one(
            "SELECT MAX(last_scammer_at - approved_at) AS span FROM threads "
            "WHERE first_bite_at IS NOT NULL AND approved_at IS NOT NULL")
        t["longest_hook_s"] = (longest or {}).get("span") or 0
        return t
