"""Clients for AgentMail (Uncle's inbox), Jev (decisions) and Ollama (Uncle's voice).

Each has a Mock twin so the whole loop runs and tests offline.
"""
import itertools
import json
import re
import time
import urllib.parse

from . import gateway, net


def _q(s):
    return urllib.parse.quote(s, safe="")


# --------------------------------------------------------------------------- AgentMail
class AgentMail:
    def __init__(self, endpoint=None):
        self._ep = endpoint

    @property
    def ep(self):
        if self._ep is None:
            self._ep = gateway.resolve("agentmail")
        return self._ep

    def _call(self, method, path, body=None, timeout=30):
        return net.request(method, self.ep.url("/v0" + path), body, self.ep.headers, timeout=timeout)

    def create_inbox(self, username, display_name):
        return self._call("POST", "/inboxes", {"username": username, "display_name": display_name})

    def list_inboxes(self):
        return self._call("GET", "/inboxes")

    # Per-inbox webhook endpoints: an inbox-scoped key can use these, and the Fly AgentMail
    # connector allows them (it blocks the organization-level /v0/webhooks).
    def create_webhook(self, url, inbox_id):
        return self._call("POST", f"/inboxes/{_q(inbox_id)}/webhooks", {
            "url": url, "event_types": ["message.received"], "client_id": "uncle-vern-wake"})

    def list_webhooks(self, inbox_id):
        return self._call("GET", f"/inboxes/{_q(inbox_id)}/webhooks")

    def get_message(self, inbox_id, message_id, thread_id=None):
        try:
            return self._call("GET", f"/inboxes/{_q(inbox_id)}/messages/{_q(message_id)}")
        except net.HttpError as exc:
            if exc.status != 403:
                raise
        # The Fly AgentMail connector blocks single-message reads, but a thread read carries
        # every message in full, so find the message's thread and take it from there.
        if not thread_id:
            for m in self.list_messages(inbox_id, limit=100).get("messages", []):
                if m.get("message_id") == message_id:
                    thread_id = m.get("thread_id")
                    break
        if thread_id:
            thread = self._call("GET", f"/inboxes/{_q(inbox_id)}/threads/{_q(thread_id)}")
            for m in (thread or {}).get("messages", []):
                if m.get("message_id") == message_id:
                    return m
        raise net.HttpError(404, "message not found in its thread", message_id)

    def list_messages(self, inbox_id, limit=50):
        # AgentMail files forwarded scams and scammers' replies under spam, which a plain listing hides.
        return self._call("GET", f"/inboxes/{_q(inbox_id)}/messages?limit={limit}&include_spam=true")

    def get_attachment(self, inbox_id, message_id, attachment_id):
        meta = self._call("GET", f"/inboxes/{_q(inbox_id)}/messages/{_q(message_id)}/attachments/{_q(attachment_id)}")
        if isinstance(meta, dict) and meta.get("download_url"):
            return net.request("GET", meta["download_url"], timeout=30)
        return meta

    def send(self, inbox_id, to, subject, text):
        return self._call("POST", f"/inboxes/{_q(inbox_id)}/messages/send",
                          {"to": to, "subject": subject, "text": text})

    def reply(self, inbox_id, message_id, text):
        return self._call("POST", f"/inboxes/{_q(inbox_id)}/messages/{_q(message_id)}/reply", {"text": text})


class MockAgentMail:
    """An in-memory inbox. deliver() simulates mail arriving; outbox records what Uncle sent."""

    def __init__(self, inbox="uncle@agentmail.test"):
        self.inbox = inbox
        self.messages = {}
        self.outbox = []
        self._ids = itertools.count(1)

    def deliver(self, sender, subject, text, thread_id=None, attachments=None, raw_attachments=None):
        mid = f"<m{next(self._ids)}@mock>"
        tid = thread_id or f"t-{mid}"
        self.messages[mid] = {
            "inbox_id": self.inbox, "message_id": mid, "thread_id": tid, "from": sender,
            "to": [self.inbox], "subject": subject, "text": text, "extracted_text": text,
            "labels": ["received"], "attachments": attachments or [], "timestamp": time.time(),
            "_raw_attachments": raw_attachments or {},
        }
        return mid, tid

    def get_message(self, inbox_id, message_id, thread_id=None):
        if message_id not in self.messages:
            raise net.HttpError(404, "not found", message_id)
        return self.messages[message_id]

    def list_messages(self, inbox_id, limit=50):
        items = sorted(self.messages.values(), key=lambda m: m["timestamp"], reverse=True)
        return {"messages": items[:limit]}

    def get_attachment(self, inbox_id, message_id, attachment_id):
        return self.messages[message_id]["_raw_attachments"][attachment_id]

    def send(self, inbox_id, to, subject, text):
        mid = f"<s{next(self._ids)}@mock>"
        tid = f"t-{mid}"
        self.outbox.append({"kind": "send", "to": to, "subject": subject, "text": text,
                            "message_id": mid, "thread_id": tid})
        return {"message_id": mid, "thread_id": tid}

    def reply(self, inbox_id, message_id, text):
        orig = self.messages.get(message_id, {})
        mid = f"<r{next(self._ids)}@mock>"
        self.outbox.append({"kind": "reply", "in_reply_to": message_id, "text": text,
                            "message_id": mid, "thread_id": orig.get("thread_id")})
        return {"message_id": mid, "thread_id": orig.get("thread_id")}


# --------------------------------------------------------------------------- Jev
DECIDERS = {
    # service in gateway.SERVICES, default model, the name the page uses, who makes it
    "typesafe": ("jev", "jev-latest", "Jev", "TypeSafe"),
    "ollama": ("ollama", "clef", "Clef", "Ollama"),
}


class Jev:
    """A System One decision model: every answer is a number, not prose.

    TypeSafe's Jev by default. Ollama serves the same API (POST /v1/systemone, same
    questions) with its own model, Clef, so one Ollama key can cover decisions too.
    """

    def __init__(self, endpoint=None, model=None, provider="typesafe"):
        service, default_model, self.name, self.maker = DECIDERS[provider]
        self.about = f"{self.maker}'s decision model"
        self.provider = provider
        self.service = service
        self._ep = endpoint
        self.model = model or default_model

    @property
    def ep(self):
        if self._ep is None:
            self._ep = gateway.resolve(self.service)
        return self._ep

    def ask(self, state, questions):
        body = {"model": self.model, "state": state, "questions": questions}
        res = net.request("POST", self.ep.url("/v1/systemone"), body, self.ep.headers, timeout=60)
        return res.get("answers", {})


def noul(instructions):
    return {"type": "noul", "instructions": instructions}


def choice(instructions, criteria):
    return {"type": "choice", "instructions": instructions, "criteria": criteria}


def score(instructions, levels):
    return {"type": "score", "instructions": instructions, "criteria": levels}


def listing(instructions, most=4):
    """A short list of plain-words items. Only deciders with `lists = True` (Claude) can answer one."""
    return {"type": "list", "instructions": instructions, "most": most}


def listed(answers, key):
    a = answers.get(key) or {}
    return [x.strip() for x in (a.get("items") or []) if isinstance(x, str) and x.strip()]


def p_yes(answers, key, default=0.0):
    a = answers.get(key) or {}
    v = a.get("noul")
    return float(v) if isinstance(v, (int, float)) else default


def picked(answers, key, default=None):
    a = answers.get(key) or {}
    return a.get("choice", default), float(a.get("confidence") or 0.0)


def scored(answers, key, default=0.0):
    a = answers.get(key) or {}
    v = a.get("score")
    return float(v) if isinstance(v, (int, float)) else default


SCAM_WORDS = re.compile(
    r"inheritance|beneficiary|lottery|winner|million|usd|fund|barrister|next of kin|"
    r"western union|gift card|bitcoin|crypto|wire|transfer|processing fee|urgent|"
    r"compensation|consignment|claim|bank details|kindly|dear friend|renewal|invoice",
    re.I)


class MockJev:
    """Keyword heuristics shaped like Jev's answers, for offline runs."""

    name, maker, provider, about = "Jev", "TypeSafe", "mock", "TypeSafe's decision model"

    def __init__(self):
        self.calls = []

    def ask(self, state, questions):
        text = state if isinstance(state, str) else json.dumps(state)
        self.calls.append((text, list(questions)))
        if isinstance(state, dict) and "their_reply" in state:
            text = state["their_reply"] + " " + state.get("original_email", "")
        hits = len(SCAM_WORDS.findall(text))
        p_scam = min(0.99, 0.15 + 0.17 * hits)
        low = text.lower()
        out = {}
        for key, q in questions.items():
            if q["type"] == "noul":
                instr = q["instructions"].lower()
                if "approv" in instr or "go ahead" in instr:
                    yes = bool(re.search(r"\b(yes|yep|send|go ahead|do it|ok)\b", low))
                    out[key] = {"type": "noul", "noul": 0.95 if yes else 0.05}
                elif "stop" in instr:
                    stop = bool(re.search(r"\b(stop|unsubscribe|leave me alone|wrong person)\b", low))
                    out[key] = {"type": "noul", "noul": 0.9 if stop else 0.04}
                elif "continue" in instr:
                    out[key] = {"type": "noul", "noul": 0.8}
                elif "reply by email" in instr or "write to" in instr:
                    out[key] = {"type": "noul", "noul": 0.9 if "@" in text or "reply" in low else 0.3}
                else:
                    out[key] = {"type": "noul", "noul": p_scam}
            elif q["type"] == "choice":
                names = list(q["criteria"])
                pick = names[0]
                if "approve" in names:
                    if re.search(r"\b(hide)\b", low):
                        pick = "hide"
                    elif re.search(r"\b(no|don't|dont|stop|nope)\b", low):
                        pick = "decline"
                    elif re.search(r"\b(yes|yep|send|go ahead|do it|ok)\b", low):
                        pick = "approve"
                    else:
                        pick = "other"
                elif "gift_cards" in names and "gift card" in low:
                    pick = "gift_cards"
                elif "money_transfer" in names and re.search(r"western union|wire|transfer", low):
                    pick = "money_transfer"
                elif "advance_fee" in names and re.search(r"inheritance|lottery|fund|beneficiary", low):
                    pick = "advance_fee"
                probs = {n: (0.8 if n == pick else 0.2 / max(1, len(names) - 1)) for n in names}
                out[key] = {"type": "choice", "choice": pick, "confidence": 0.8, "probabilities": probs}
            elif q["type"] == "score":
                n = len(q["criteria"])
                angry = len(re.findall(r"!|urgent|now|immediately|waste|stupid|why", low))
                val = min(n - 1, angry * 0.7)
                out[key] = {"type": "score", "score": val, "confidence": 0.6}
            elif q["type"] == "list":
                if "red flag" in q["instructions"].lower() or key == "red_flags":
                    items = [flag for word, flag in MOCK_FLAGS if word in low]
                else:  # a sentence quoted from the email
                    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.split()) >= 8]
                    items = [" ".join(sentences[0].split()[:12])] if sentences else []
                out[key] = {"type": "list", "items": items[:q.get("most", 4)]}
        return out

    lists = True


MOCK_FLAGS = [("fee", "asks for a fee before you get paid"), ("next of kin", "a stranger says you are owed money"),
              ("urgent", "rushes you"), ("bank details", "asks for your bank details"),
              ("inheritance", "money from someone you never knew")]


# --------------------------------------------------------------------------- Ollama
class Ollama:
    """Uncle's voice. `model` may be a comma list: the first one this account can use wins.

    The free plan only covers some starter models, so a list like
    "gpt-oss:120b,gpt-oss:20b,gemma4" keeps Uncle writing whatever the plan allows.
    """

    name, maker = "Ollama", "Ollama Cloud"
    # Statuses that mean "this account can't use that model", not "the service is down".
    SKIP = (400, 401, 402, 403, 404)

    def __init__(self, endpoint=None, model="gpt-oss:120b", think="low"):
        self._ep = endpoint
        self.models = [m.strip() for m in str(model).split(",") if m.strip()]
        self.model = self.models[0]
        self.think = think

    @property
    def ep(self):
        if self._ep is None:
            self._ep = gateway.resolve("ollama")
        return self._ep

    def _body(self, model, messages, temperature, max_tokens):
        body = {"model": model, "messages": messages, "stream": False,
                "options": {"temperature": temperature, "num_predict": max_tokens}}
        if model.startswith("gpt-oss") and self.think in ("low", "medium", "high"):
            body["think"] = self.think
        elif self.think in ("true", "false"):
            body["think"] = self.think == "true"
        return body

    def chat(self, messages, temperature=0.9, max_tokens=900):
        order = [self.model] + [m for m in self.models if m != self.model]
        last = None
        for model in order:
            try:
                res = net.request("POST", self.ep.url("/api/chat"),
                                  self._body(model, messages, temperature, max_tokens), self.ep.headers, timeout=120)
            except net.HttpError as exc:
                if exc.status in self.SKIP and model != order[-1]:
                    last = exc
                    continue
                raise
            self.model = model  # remember the one that worked
            return ((res or {}).get("message") or {}).get("content", "").strip()
        raise last or RuntimeError("no model answered")


MOCK_LETTERS = [
    "Well hello there!\n\nI read your letter twice at the kitchen table and I have to say this is the best news "
    "I've had since the Buick passed inspection. I went down to the Piggly Wiggly to ask about the Western Union "
    "but Doug got out of the car and into the bread aisle and by the time I caught him the lady said they were "
    "closing up.\n\nBefore I go back Tuesday, can you tell me again which counter it is? The one by the lottery "
    "tickets or the one by the pharmacy?\n\nYours truly,\nVern",
    "Dear friend,\n\nI am SO sorry for the wait. I had the card all filled out and Doug took it under the couch. "
    "I got most of it back but he chewed the corner where the numbers go. My neighbor Darlene says that happens "
    "to her too but she is a liar about most things.\n\nShould I go get a new card or can you work with half of "
    "one? I'd hate to waste it.\n\nUncle Vern",
]


class MockOllama:
    name, maker = "Ollama", "Ollama Cloud"

    def __init__(self):
        self.calls = []
        self._i = itertools.count()

    def chat(self, messages, temperature=0.9, max_tokens=900):
        self.calls.append(messages)
        return MOCK_LETTERS[next(self._i) % len(MOCK_LETTERS)]
