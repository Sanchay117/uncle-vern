"""Uncle's front door: the web page, the try box, and the AgentMail webhook."""
import json
import os
import queue
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import awake, card, claude, clients, gateway, memory, meter, redact, voice, web, websearch
from .config import Config
from .engine import Engine
from .store import Store

MAX_BODY = 1_000_000


def _has(service):
    try:
        gateway.resolve(service)
        return True
    except Exception:  # noqa: BLE001
        return False


def pick_decider(setting):
    """Jev if there's a TypeSafe connector, else Claude if there's an Anthropic one, else Clef on Ollama."""
    if setting in clients.DECIDERS or setting == "anthropic":
        return setting
    if _has("jev"):
        return "typesafe"
    if _has("anthropic"):
        return "anthropic"
    return "ollama"


def pick_writer(setting):
    """Claude if there's an Anthropic connector (Ollama's free plan covers no chat models), else Ollama."""
    if setting in ("ollama", "anthropic"):
        return setting
    return "anthropic" if _has("anthropic") else "ollama"


class App:
    def __init__(self, cfg=None, mail=None, jev=None, llm=None):
        self.cfg = cfg or Config()
        self.store = Store(self.cfg.db_path)
        if self.cfg.mock:
            mail = mail or clients.MockAgentMail(self.cfg.inbox or "uncle@agentmail.test")
            jev = jev or clients.MockJev()
            llm = llm or clients.MockOllama()
        self.mail = mail or clients.AgentMail()
        if jev is None or llm is None:
            shared = claude.Claude()  # one client if Claude does both jobs
            if jev is None:
                decider = pick_decider(self.cfg.decider)
                jev = shared if decider == "anthropic" else \
                    clients.Jev(model=self.cfg.decider_model, provider=decider)
            if llm is None:
                llm = shared if pick_writer(self.cfg.writer) == "anthropic" else \
                    clients.Ollama(model=self.cfg.model, think=self.cfg.think)
        self.jev, self.llm = jev, llm
        web.DECIDER.update(name=jev.name, maker=jev.maker, about=jev.about)
        web.VOICE.update(name=llm.name, maker=llm.maker)
        embedder = memory.WordsEmbedder() if self.cfg.mock else memory.PineconeEmbedder()
        self.memory = memory.Memory(self.store, embedder, same=self.cfg.memory_same)
        speaker = voice.MockSpeaker() if self.cfg.mock else voice.Deepgram(self.cfg.voice_model)
        self.voice = voice.Voice(os.path.join(os.path.dirname(os.path.abspath(self.cfg.db_path)), "voice"),
                                 speaker, per_day=self.cfg.voice_per_day)
        searcher = websearch.MockSearch() if self.cfg.mock else websearch.ApifySearch()
        self.web = websearch.WebCheck(self.store, searcher, per_day=self.cfg.web_per_day)
        self.engine = Engine(self.cfg, self.store, self.mail, self.jev, self.llm, memory=self.memory, web=self.web)
        self.meter = meter.Meter(self.store)
        self.jobs = queue.Queue()
        self.cards = {}  # key -> (version, png)
        self.last_rounds = 0.0

    def start_background(self):
        self.meter.start()
        threading.Thread(target=self._worker, daemon=True, name="worker").start()
        self.queue_rounds()

    def queue_rounds(self, every=900):
        """Ask for a mailbox check, at most once every `every` seconds. Any visit can wake him, and an hourly
        ping from outside makes sure one does."""
        now = time.time()
        if now - self.last_rounds < every:
            return False
        self.last_rounds = now
        self.jobs.put(("rounds", None))
        return True

    def _worker(self):
        while True:
            kind, arg = self.jobs.get()
            try:
                # Without a hold the Sprite can pause mid-letter, after a webhook has had its 200.
                with awake.held():
                    if kind == "message":
                        self.engine.handle(arg)
                    elif kind == "catch_up":
                        self.engine.catch_up()
                    elif kind == "rounds":
                        self.engine.rounds()
            except Exception as exc:  # noqa: BLE001
                self.store.note(f"Worker error: {exc}", kind="error", public=False)

    # -- views
    def meter_stats(self):
        return meter.stats(self.store, self.meter.boot_id)

    def _public_thread(self, tid):
        t = self.store.thread(tid)
        if not t or t["hidden"] or t["status"] not in ("active", "closed") or not t["approved_at"]:
            return None
        return t

    def _letters(self, t):
        """A conversation's letters for the page, with the scammer's names blacked out of Uncle's too."""
        rows = self.store.letters(t["id"])
        names = [t["scammer_name"]] + redact.names_in(t["scam_text"])
        names += [n for l in rows if l["direction"] == "scammer" for n in redact.names_in(l["body"])]
        names = [n for n in names if n]
        for l in rows:
            if l["direction"] == "uncle" and l["public_body"]:
                l["public_body"] = redact.hide_names(l["public_body"], names)
        return rows

    def _card_spec(self, key):
        """(version, spec) for a share card: 'home' or a thread id. The version changes with each letter."""
        if key == "home":
            threads = self.store.public_threads()
            mine = [l for t in threads for l in self._letters(t) if l["direction"] == "uncle" and l["public_body"]]
            mine = max(mine, key=lambda l: l["sent_at"] or 0) if mine else None
            totals = self.store.totals()
            return (f"{totals['uncle_letters']}-{totals['scammer_letters']}-{len(threads)}",
                    web.home_share(self.cfg, totals, mine))
        t = self._public_thread(key)
        if not t:
            return None, None
        letters = self._letters(t)
        return f"{len(letters)}-{t['status']}", web.thread_share(self.cfg, t, letters)

    def card_url(self, key):
        if not card.available():
            return None
        version, _ = self._card_spec(key)
        return f"{self.cfg.public_url}/card/{key}.png?v={version}" if version else None

    def card_png(self, key):
        if not card.available():
            return None
        version, spec = self._card_spec(key)
        if not spec:
            return None
        hit = self.cards.get(key)
        if hit and hit[0] == version:
            return hit[1]
        png = card.render(**spec)
        self.cards[key] = (version, png)
        return png

    def home_html(self):
        threads = self.store.public_threads()
        letters = {t["id"]: self._letters(t) for t in threads}
        theirs = [l for ls in letters.values() for l in ls if l["direction"] == "scammer" and l["public_body"]]
        latest = max(theirs, key=lambda l: l["sent_at"] or 0) if theirs else None
        if latest is None:
            # No reply yet: put the newest real scam Uncle is answering on the desk, not an empty tray.
            open_ = [t for t in threads if t["scam_text"]]
            if open_:
                t = max(open_, key=lambda t: t["approved_at"] or 0)
                latest = {"public_body": web.original_scam(t), "sent_at": t["approved_at"],
                          "label": "A real scam he's answering"}
        return web.home(self.cfg, self.store.totals(), self.meter_stats(), threads, letters,
                        self.store.diary(25), gateway.keys_on_box(), latest_scam=latest,
                        wakes=self.store.q("SELECT started_at, last_seen FROM boots WHERE last_seen>=?",
                                           (time.time() - 86400,)),
                        card=self.card_url("home"), families=self.families(),
                        memory_name=self.memory.name if self.memory.available() else None,
                        voice_name=self.voice.name if self.voice.available() else None,
                        web_name=self.web.name if self.web.available() else None,
                        capped_until=self._capped())

    def _capped(self):
        until = self.engine.mail_blocked_until()
        return until if until > time.time() else None

    def kin(self, t):
        """The other conversations with the same script, either way round: [(row, score)], public ones only,
        plus how many more Uncle saw but never wrote to."""
        scores = dict(memory.kin_of(t))
        for o in self.store.q("SELECT id, kin FROM threads WHERE kin LIKE ?", (f"%[{t['id']},%",)):
            for k, s in memory.kin_of(o):
                if k == t["id"]:
                    scores[o["id"]] = max(scores.get(o["id"], 0), s)
        public, hidden = [], 0
        for k, s in sorted(scores.items(), key=lambda p: -p[1]):
            row = self._public_thread(k)
            if row:
                public.append((row, s))
            else:
                hidden += 1
        return public, hidden

    def families(self):
        """Scripts Uncle has had more than once: [{'public': [rows], 'n': size, 'addresses': distinct addresses}]."""
        rows = self.store.q("SELECT id, kin, scammer_addr FROM threads WHERE scam_text IS NOT NULL AND scam_text != ''")
        by_id = {r["id"]: r for r in rows}
        out = []
        for group in memory.families(rows):
            public = [p for p in (self._public_thread(i) for i in group) if p]
            if public:
                out.append({"public": public, "n": len(group),
                            "addresses": len({by_id[i]["scammer_addr"] for i in group if by_id[i]["scammer_addr"]})})
        return out

    def thread_html(self, tid):
        t = self._public_thread(tid)
        if not t:
            return None
        return web.thread_page(self.cfg, self.meter_stats(), t, self._letters(t),
                               self.store.diary(50, tid), card=self.card_url(tid), kin=self.kin(t),
                               memory_name=self.memory.name, voice_on=self.voice.available(),
                               web_name=self.web.name)

    def letter_audio(self, lid):
        """Uncle's own letter, read aloud, from a conversation on the page. None for anything else."""
        row = self.store.one("SELECT thread_id FROM letters WHERE id=? AND direction='uncle'", (lid,))
        t = self._public_thread(row["thread_id"]) if row else None
        if not t:
            return None
        text = next((l["public_body"] for l in self._letters(t) if l["id"] == lid), None)
        return self.voice.audio(text) if text else None

    def with_voice(self, j):
        """Give a practice letter a link to hear it read, when Uncle has a voice."""
        if j.get("letter") and self.voice.available():
            j["voice"] = f"/voice/try/{self.voice.remember_try(j['letter'])}.mp3"
        return j

    def stats(self):
        return {"totals": self.store.totals(), "meter": self.meter_stats(), "keys_on_box": gateway.keys_on_box(),
                "active": len(self.store.active_threads())}


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        server_version = "UncleVern/1.0"

        def log_message(self, fmt, *args):  # quieter logs
            pass

        def _send(self, code, body, ctype="text/html; charset=utf-8", cache="no-store"):
            data = body.encode() if isinstance(body, str) else body
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", cache)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def _json(self, code, obj):
            self._send(code, json.dumps(obj), "application/json")

        def _ip(self):
            fwd = self.headers.get("Fly-Client-IP") or self.headers.get("X-Forwarded-For") or ""
            return fwd.split(",")[0].strip() or self.client_address[0]

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                return None
            return self.rfile.read(n) if n else b""

        def do_GET(self):
            app.meter.touch()
            path = self.path.split("?")[0]
            try:
                if path == "/rounds":
                    return self._json(200, {"queued": app.queue_rounds(every=300)})
                if path in ("/", "/healthz") or path.startswith("/t/"):
                    app.queue_rounds()
                if path == "/":
                    return self._send(200, app.home_html())
                m = re.fullmatch(r"/t/(\d+)", path)
                if m:
                    h = app.thread_html(int(m.group(1)))
                    return self._send(200, h) if h else self._send(404, web.page("Not here", "<p>No such letter.</p>"))
                m = re.fullmatch(r"/card/(home|\d+)\.png", path)
                if m:
                    key = m.group(1)
                    png = app.card_png(key if key == "home" else int(key))
                    if not png:
                        return self._send(404, web.page("Not here", "<p>No such card.</p>"))
                    return self._send(200, png, "image/png", cache="public, max-age=300")
                m = re.fullmatch(r"/voice/(letter|try)/(\d+|[0-9a-f]{32})\.mp3", path)
                if m:
                    return self._voice(*m.groups())
                if path == "/api/stats":
                    return self._json(200, app.stats())
                if path == "/healthz":
                    return self._json(200, {"ok": True, "t": time.time()})
                if path == "/favicon.ico":
                    return self._send(204, b"", "image/x-icon", cache="max-age=86400")
                return self._send(404, web.page("Not here", "<p>No such page.</p>"))
            except Exception as exc:  # noqa: BLE001
                return self._send(500, web.page("Oops", f"<p>Uncle tripped over Doug. ({web.esc(exc)})</p>"))

        def _voice(self, kind, key):
            nope = web.page("Not here", "<p>Uncle can't read that one out.</p>")
            try:
                if kind == "letter":
                    audio = app.letter_audio(int(key)) if key.isdigit() else None
                else:
                    text = app.voice.try_text(key)
                    audio = app.voice.audio(text) if text else None
            except Exception as exc:  # noqa: BLE001
                app.store.note(f"Voice error: {exc}", kind="error", public=False)
                return self._send(503, nope)  # the page falls back to the browser's own voice
            if not audio:
                return self._send(404, nope)
            return self._send(200, audio, "audio/mpeg", cache="public, max-age=86400")

        def do_POST(self):
            app.meter.touch()
            path = self.path.split("?")[0]
            raw = self._body()
            if raw is None:
                return self._json(413, {"error": "too big"})
            try:
                data = json.loads(raw or b"{}")
            except ValueError:
                return self._json(400, {"error": "bad json"})
            if path == "/webhook/agentmail":
                # The webhook only tells Uncle where to look. He re-reads the message from his
                # own inbox through the gateway, so a forged webhook can't put words in it.
                # message.received and its variants (spam included); a blocked message was never stored.
                event = str(data.get("event_type") or "")
                if event.startswith("message.received") and not event.endswith(".blocked"):
                    mid = (data.get("message") or {}).get("message_id")
                    if mid:
                        app.jobs.put(("message", mid))
                return self._json(200, {"ok": True})
            if path == "/api/try/reply":
                try:
                    return self._json(200, app.with_voice(app.engine.try_reply(
                        data.get("scam"), data.get("turns"), data.get("reply"), self._ip())))
                except Exception as exc:  # noqa: BLE001
                    app.store.note(f"Try reply error: {exc}", kind="error", public=False)
                    return self._json(200, {"error": "Uncle dropped the phone. Try again in a minute."})
            if path == "/api/try":
                try:
                    return self._json(200, app.with_voice(app.engine.try_uncle(data.get("text", ""), self._ip())))
                except Exception as exc:  # noqa: BLE001
                    app.store.note(f"Try box error: {exc}", kind="error", public=False)
                    return self._json(200, {"error": "Uncle dropped the phone. Try again in a minute."})
            return self._json(404, {"error": "not found"})

    return Handler


def main():
    app = App()
    app.start_background()
    srv = ThreadingHTTPServer(("0.0.0.0", app.cfg.port), make_handler(app))
    print(f"Uncle Vern listening on :{app.cfg.port} (mock={app.cfg.mock})", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
