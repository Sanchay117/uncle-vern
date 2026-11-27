"""Uncle's memory for scripts: has he had this letter before, from somebody else?

Scam gangs send one script from many addresses, and the addresses get shut down while the script lives on.
Pinecone's hosted reranker (bge-reranker-v2-m3, on Pinecone's free Starter plan) compares a new scam with the
ones already on Uncle's disk and says how alike they are. Matches above a bar are the same family.

Without a Pinecone connector Uncle simply has no memory for scripts; nothing else changes.
"""
import json
import re
import threading
import time

from . import gateway, net

MODEL = "bge-reranker-v2-m3"
API_VERSION = "2025-04"
QUERY_CHARS = 1500
DOC_CHARS = 2500


def scam_doc(subject, text):
    return f"Subject: {subject or ''}\n\n{text or ''}".strip()


class PineconeRanker:
    """Pinecone's rerank endpoint, through the Sprites connector (or a key, off the Sprite)."""
    name = "Pinecone"

    def __init__(self):
        self._ep = None
        self._missing_until = 0.0
        self._lock = threading.Lock()

    def available(self):
        with self._lock:
            if self._ep:
                return True
            if time.time() < self._missing_until:
                return False
            try:
                self._ep = gateway.resolve("pinecone")
                return True
            except Exception:  # noqa: BLE001  (no connector yet: ask the gateway again in ten minutes)
                self._missing_until = time.time() + 600
                return False

    def rank(self, query, docs, top_n):
        """[(index into docs, score 0..1)], best first."""
        if not self.available():
            return []
        body = {"model": MODEL, "query": query[:QUERY_CHARS],
                "documents": [{"id": str(i), "text": d[:DOC_CHARS]} for i, d in enumerate(docs)],
                "top_n": top_n, "return_documents": False, "parameters": {"truncate": "END"}}
        res = net.request("POST", self._ep.url("/rerank"), body,
                          headers={**self._ep.headers, "X-Pinecone-API-Version": API_VERSION}, timeout=30)
        return [(int(d["index"]), float(d["score"])) for d in (res or {}).get("data", [])]


class WordsRanker:
    """For tests and local runs: share of words in common. Same shape as Pinecone's answer."""
    name = "word overlap"

    def available(self):
        return True

    def rank(self, query, docs, top_n):
        def words(s):
            return set(re.findall(r"[a-z]{3,}", s.lower()))
        q = words(query)
        scored = [(i, len(q & words(d)) / max(1, len(q | words(d)))) for i, d in enumerate(docs)]
        return sorted(scored, key=lambda p: -p[1])[:top_n]


class Memory:
    def __init__(self, store, ranker, same=0.75):
        self.store = store
        self.ranker = ranker
        self.same = same

    @property
    def name(self):
        return self.ranker.name

    def available(self):
        return self.ranker.available()

    def recall(self, subject, text, exclude=None, limit=100):
        """Earlier scams this one is the same script as: [(thread id, score)], best first."""
        rows = self.store.q("SELECT id, scam_subject, scam_text FROM threads WHERE id != ? AND scam_text IS NOT NULL "
                            "AND scam_text != '' ORDER BY id DESC LIMIT ?", (exclude or -1, limit))
        if not rows or not self.available():
            return []
        hits = self.ranker.rank(scam_doc(subject, text), [scam_doc(r["scam_subject"], r["scam_text"]) for r in rows],
                                top_n=min(5, len(rows)))
        return [(rows[i]["id"], round(s, 3)) for i, s in hits if s >= self.same]

    def remember(self, tid):
        """Work out and keep a thread's kin. Returns the list, or None when there's no memory to ask."""
        t = self.store.thread(tid)
        if not t or not t["scam_text"] or not self.available():
            return None
        kin = self.recall(t["scam_subject"], t["scam_text"], exclude=tid)
        self.store.update_thread(tid, kin=json.dumps(kin))
        return kin

    def backfill(self, limit=20):
        """Threads from before Uncle had a memory."""
        if not self.available():
            return 0
        n = 0
        for r in self.store.q("SELECT id FROM threads WHERE kin IS NULL AND scam_text IS NOT NULL AND scam_text != '' "
                              "ORDER BY id LIMIT ?", (limit,)):
            if self.remember(r["id"]) is not None:
                n += 1
        return n


def kin_of(thread):
    try:
        return [(int(t), float(s)) for t, s in json.loads(thread.get("kin") or "[]")]
    except (ValueError, TypeError):
        return []


def families(threads):
    """Group threads that share a script. threads: rows with id and kin. Returns lists of ids, biggest first,
    only groups of two or more."""
    parent = {t["id"]: t["id"] for t in threads}

    def root(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for t in threads:
        for other, _ in kin_of(t):
            if other in parent:
                parent[root(t["id"])] = root(other)
    groups = {}
    for tid in parent:
        groups.setdefault(root(tid), []).append(tid)
    return sorted((sorted(g) for g in groups.values() if len(g) > 1), key=lambda g: (-len(g), g[0]))
