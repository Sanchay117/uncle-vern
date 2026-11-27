"""Uncle's memory for scripts: has he had this letter before, from somebody else?

Scam gangs send one script from many addresses, and the addresses get shut down while the script lives on.
Pinecone's hosted embedding model (llama-text-embed-v2, on Pinecone's free Starter plan) turns each scam into a
vector, kept on Uncle's disk. Two scams whose vectors point the same way are the same script.

Measured on Uncle's real mail (Nov 27): three copies of one NESREA letter from three addresses scored 0.986 to
0.995 against each other; every other pair scored 0.45 or less. Pinecone's reranker, tried first, couldn't tell
them apart (0.10 to 0.27 for the copies, 0.27 for an unrelated romance scam).

Without a Pinecone connector Uncle simply has no memory for scripts; nothing else changes.
"""
import array
import base64
import hashlib
import json
import math
import re
import threading
import time

from . import gateway, net

MODEL = "llama-text-embed-v2"
API_VERSION = "2025-04"
TEXT_CHARS = 2000
BATCH = 90  # Pinecone takes up to 96 inputs a request


def scam_text(text):
    """What gets compared: the letter itself, not the subject line, which scammers change every time."""
    return " ".join((text or "").split())[:TEXT_CHARS]


def _unit(v):
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def cosine(a, b):
    return sum(x * y for x, y in zip(a, b))  # both are unit length


def pack(v):
    return base64.b64encode(array.array("f", v).tobytes()).decode()


def unpack(s):
    try:
        a = array.array("f")
        a.frombytes(base64.b64decode(s))
        return list(a)
    except (ValueError, TypeError):
        return None


class PineconeEmbedder:
    """Pinecone's embed endpoint, through the Sprites connector (or a key, off the Sprite)."""
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

    def embed(self, texts):
        """Unit vectors, one per text."""
        out = []
        for i in range(0, len(texts), BATCH):
            body = {"model": MODEL, "inputs": [{"text": t} for t in texts[i:i + BATCH]],
                    "parameters": {"input_type": "passage", "truncate": "END"}}
            res = net.request("POST", self._ep.url("/embed"), body,
                              headers={**self._ep.headers, "X-Pinecone-API-Version": API_VERSION}, timeout=60)
            out += [_unit(d["values"]) for d in (res or {}).get("data", [])]
        if len(out) != len(texts):
            raise RuntimeError(f"Pinecone sent {len(out)} vectors for {len(texts)} scams")
        return out


class WordsEmbedder:
    """For tests and local runs: hashed word counts. Same shape as Pinecone's answer."""
    name = "word overlap"

    def available(self):
        return True

    def embed(self, texts):
        out = []
        for t in texts:
            v = [0.0] * 256
            for w in re.findall(r"[a-z]{3,}", t.lower()):
                v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 256] += 1.0
            out.append(_unit(v))
        return out


class Memory:
    def __init__(self, store, embedder, same=0.85):
        self.store = store
        self.embedder = embedder
        self.same = same
        self._lock = threading.Lock()

    @property
    def name(self):
        return self.embedder.name

    def available(self):
        return self.embedder.available()

    def _vectors(self, rows):
        """{thread id: vector} for these rows, asking Pinecone only for the ones not on disk yet."""
        out, todo = {}, []
        for r in rows:
            v = unpack(r["vec"]) if r["vec"] else None
            if v:
                out[r["id"]] = v
            elif r["scam_text"]:
                todo.append(r)
        if todo:
            for r, v in zip(todo, self.embedder.embed([scam_text(r["scam_text"]) for r in todo])):
                self.store.update_thread(r["id"], vec=pack(v))
                out[r["id"]] = v
        return out

    def recall(self, tid, limit=500):
        """Other scams this one is the same script as: [(thread id, score)], best first, at most five."""
        rows = self.store.q("SELECT id, scam_text, vec FROM threads WHERE scam_text IS NOT NULL AND scam_text != '' "
                            "ORDER BY id DESC LIMIT ?", (limit,))
        if not any(r["id"] == tid for r in rows) or not self.available():
            return []
        with self._lock:
            vecs = self._vectors(rows)
        mine = vecs.get(tid)
        if not mine:
            return []
        scored = sorted(((k, round(cosine(mine, v), 3)) for k, v in vecs.items() if k != tid), key=lambda p: -p[1])
        return [(k, s) for k, s in scored[:5] if s >= self.same]

    def match_text(self, text, limit=500):
        """A pasted scam against every scam Uncle has had: ([(thread id, score)] at most five, how many compared)."""
        if not (text or "").strip() or not self.available():
            return [], 0
        rows = self.store.q("SELECT id, scam_text, vec FROM threads WHERE scam_text IS NOT NULL AND scam_text != '' "
                            "ORDER BY id DESC LIMIT ?", (limit,))
        with self._lock:
            vecs = self._vectors(rows)
        mine = self.embedder.embed([scam_text(text)])[0]
        scored = sorted(((k, round(cosine(mine, v), 3)) for k, v in vecs.items()), key=lambda p: -p[1])
        return [(k, s) for k, s in scored[:5] if s >= self.same], len(vecs)

    def remember(self, tid):
        """Work out and keep a thread's kin. Returns the list, or None when there's no memory to ask."""
        t = self.store.thread(tid)
        if not t or not t["scam_text"] or not self.available():
            return None
        kin = self.recall(tid)
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
