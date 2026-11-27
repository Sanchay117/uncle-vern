"""What Uncle does with each email that lands in his inbox.

Every decision is a Jev question with a number attached, and every action is
written to Uncle's diary in plain words, so anyone can see why he did it.
"""
import email.utils
import hashlib
import json
import threading
import time
import traceback

from . import intake, net, persona, redact
from .clients import choice, noul, p_yes, picked, score, scored

DAY = 86400

SCAM_TYPES = {
    "advance_fee": "Inheritance, lottery, prize, donation, compensation fund or business deal where the reader "
                   "must pay a fee or share details to receive money",
    "tech_support": "Fake renewal, invoice, refund or virus alert from a known brand, asking the reader to call or reply",
    "romance": "Romance or friendship building toward a request for money",
    "job": "Job, mystery shopper or easy-money work offer",
    "investment": "Crypto, trading or investment opportunity",
    "phishing": "Fake account, password, delivery or security alert that wants the reader to click a link or log in",
    "extortion": "Threat or blackmail, for example a claim to have compromising video",
    "probe": "A short first message from a stranger that only checks the address is live "
             "(\"is this the right email?\"), with the pitch held back for whoever replies",
    "other": "Some other kind of scam, or not a scam",
}

def intake_state(subject, body):
    return f"Subject: {subject}\n\n{body[:6000]}"


def intake_questions():
    """What the decider is asked about every forwarded email."""
    return {
        "is_scam": noul("Is this email a scam or fraud attempt: trying to get money, gift cards, crypto, "
                        "personal or banking details, or remote access from the reader under false pretenses? "
                        "Count the opening move of one too: a vague note from a stranger who only wants to "
                        "know whether the address is live, which is how many scams start before the pitch. "
                        "The reader's own family, friends or real contacts asking that are not scams."),
        "wants_email_reply": noul("Does the email ask the reader to reply by email or write to an email address?"),
        "scam_type": choice("What kind of email is this?", SCAM_TYPES),
    }


ASKING_FOR = {
    "money_transfer": "Send money by wire, Western Union, MoneyGram or bank transfer",
    "gift_cards": "Buy gift cards and send the codes",
    "crypto": "Send cryptocurrency",
    "fee": "Pay a processing, release, legal, delivery or tax fee",
    "personal_details": "Share personal, banking or ID details",
    "move_chat": "Move to WhatsApp, Telegram, a phone call or another app",
    "click_or_install": "Click a link, log in, or install an app",
    "nothing_yet": "Nothing specific yet, just building trust or asking questions",
}

FRUSTRATION = [
    "Patient and friendly",
    "Polite but pushing",
    "Impatient",
    "Annoyed",
    "Furious",
]

OWNER_COMMANDS = {
    "approve": "The owner says yes: go ahead and send Uncle's letter",
    "decline": "The owner says no: do not write to this sender",
    "hide": "The owner wants this conversation hidden from the public page",
    "other": "Something else, or unclear",
}


def addr_of(value):
    if isinstance(value, list):
        value = value[0] if value else ""
    name, addr = email.utils.parseaddr(value or "")
    return name, (addr or "").lower()


def ip_hash(ip):
    return hashlib.sha256(("uncle:" + (ip or "")).encode()).hexdigest()[:16]


def pct(p):
    return f"{round(p * 100)}%"


def is_bounce(sender, subject):
    local = (sender or "").split("@")[0]
    subject = (subject or "").lower()
    return local in ("mailer-daemon", "postmaster") or subject.startswith(
        ("delivery status notification", "undeliverable", "undelivered mail", "mail delivery failed"))


def _err(exc):
    """'HttpError 403: {"error": ...}' for the private diary."""
    return f"{exc.__class__.__name__} {getattr(exc, 'status', '')}: {str(getattr(exc, 'body', '') or exc)[:160]}"


def kind_a(kind):
    """'an advance fee', 'a romance'."""
    words = {"probe": "address-check"}.get(kind, (kind or "other").replace("_", " "))
    return ("an " if words[0] in "aeiou" else "a ") + words


class Engine:
    def __init__(self, cfg, store, mail, jev, llm):
        self.cfg = cfg
        self.store = store
        self.mail = mail
        self.jev = jev
        self.llm = llm
        self.lock = threading.Lock()

    # ------------------------------------------------------------ entry points
    def handle(self, message_id):
        """Process one inbound message by id. Safe to call twice."""
        with self.lock:
            try:
                msg = self.mail.get_message(self.cfg.inbox, message_id)
            except Exception as exc:  # noqa: BLE001
                self.store.note(f"Couldn't fetch a message ({exc.__class__.__name__}); will try again later.",
                                kind="error", public=False)
                return "fetch_failed"
            _, sender = addr_of(msg.get("from"))
            if sender == self.cfg.inbox:
                return "self"
            if "spam" in (msg.get("labels") or []) and sender not in self.cfg.owner_emails and not (
                    (msg.get("thread_id") and self.store.thread_by_am(msg["thread_id"]))
                    or self.store.active_by_scammer(sender)):
                # Spam from the boss is a forwarded scam and spam from a pen pal is a reply; the rest is noise.
                if self.store.claim_message(message_id, msg.get("thread_id"), sender):
                    self.store.finish_message(message_id, "spam")
                return "spam"
            if not self.store.claim_message(message_id, msg.get("thread_id"), sender):
                return "duplicate"
            try:
                kind, ref = self._route(msg, sender)
                self.store.finish_message(message_id, kind, thread_ref=ref)
                return kind
            except Exception as exc:  # noqa: BLE001
                self.store.finish_message(message_id, "error", status="error",
                                          detail=traceback.format_exc()[-2000:])
                self.store.note(f"Something went wrong handling a letter: {exc}", kind="error", public=False)
                return "error"

    def catch_up(self, limit=50):
        """On waking, handle anything that arrived while the webhook couldn't reach us."""
        try:
            listing = self.mail.list_messages(self.cfg.inbox, limit=limit)
        except Exception:  # noqa: BLE001
            return 0
        n = 0
        for item in reversed(listing.get("messages", [])):
            mid = item.get("message_id")
            labels = item.get("labels") or []
            if not mid or "sent" in labels:
                continue
            known = self.store.known_message(mid)
            if known and known["status"] in ("done", "processing"):
                continue
            if self.handle(mid) not in ("self", "duplicate"):
                n += 1
        return n

    # ------------------------------------------------------------ routing
    def _route(self, msg, sender):
        tid = msg.get("thread_id")
        if is_bounce(sender, msg.get("subject")):
            return "bounce", self._bounce(msg)
        if sender in self.cfg.owner_emails:
            pending = self.store.pending_by_owner_thread(tid) if tid else None
            if pending and pending["status"] == "pending_approval":
                return "owner_command", self._owner_command(msg, pending)
            if pending and pending["status"] in ("active", "closed"):
                return "owner_command", self._owner_command(msg, pending)
            return "intake", self._intake(msg)
        thread = self.store.thread_by_am(tid) if tid else None
        # A fresh-email fallback starts a new mail thread, so also know a pen pal by address.
        thread = thread or self.store.active_by_scammer(sender)
        if thread:
            return "scammer", self._scammer_letter(msg, thread)
        return "stranger", self._stranger(msg, sender)

    # ------------------------------------------------------------ owner forwards a scam
    def _intake(self, msg):
        exclude = set(self.cfg.owner_emails) | {self.cfg.inbox}
        scam = intake.extract_scam(
            msg, lambda att: self.mail.get_attachment(self.cfg.inbox, msg["message_id"], att), exclude)
        if scam is None:
            self._tell_owner(msg, "I couldn't find a forwarded email in that one. Open the scam itself, press plain "
                                  "Forward (not \"as attachment\") and send it to me.\n\nVern")
            self.store.note("Got a note from the boss with no scam inside, so I asked for the real thing.")
            return None
        a = self.jev.ask(intake_state(scam["subject"], scam["body"]), intake_questions())
        p = p_yes(a, "is_scam")
        p_reply = p_yes(a, "wants_email_reply")
        kind, _ = picked(a, "scam_type", "other")
        to = self._pick_address(scam)
        base = dict(scammer_addr=to or "", scammer_name=scam.get("from_name", ""), scam_subject=scam["subject"],
                    scam_text=scam["body"][:20000], scam_type=kind, scam_prob=p,
                    owner_thread_id=msg.get("thread_id"), owner_message_id=msg["message_id"])
        if p < self.cfg.scam_threshold:
            tid = self.store.new_thread(status="rejected", close_reason=f"{self.jev.name}: only {pct(p)} likely a scam", **base)
            self.store.note(f"{self.jev.name} rated a forwarded email only {pct(p)} likely to be a scam, so I left it alone.", tid)
            self._tell_owner(msg, f"{self.jev.name} says that one is only {pct(p)} likely to be a scam, so I'm leaving it be. "
                                  "I only write to the real thing.\n\nVern")
            return tid
        if not to:
            tid = self.store.new_thread(status="rejected", close_reason="no address to write to", **base)
            self.store.note(f"A {kind.replace('_', ' ')} scam ({pct(p)}), but there's no email address to write "
                            "back to. Probably wants a click or a call, and I don't do either.", tid)
            self._tell_owner(msg, "That one's a scam all right, but it only wants you to click or call, and I "
                                  "don't do either. Send me one that asks for a reply.\n\nVern")
            return tid
        if len(self.store.active_threads()) >= self.cfg.max_active_threads:
            tid = self.store.new_thread(status="rejected", close_reason="too many open conversations", **base)
            self._tell_owner(msg, "My plate's full right now. I'll take this one when a pen pal gives up.\n\nVern")
            return tid
        letter, problems = persona.write_letter(self.llm, persona.opening_messages(
            scam["subject"], scam["body"], pen_pals=self._pen_pals()))
        tid = self.store.new_thread(status="pending_approval", draft=letter, **base)
        self.store.note(
            f"New one from the boss: {kind_a(kind)} scam. {self.jev.name}: {pct(p)} scam, {pct(p_reply)} wants an "
            f"email back. Drafted my first letter and asked the boss before sending.", tid)
        if problems:
            self.store.note(f"My first draft broke a rule ({', '.join(sorted(set(problems)))}), so I rewrote it.",
                            tid, public=False)
        self._ask_approval(msg, tid, kind, p, to, letter)
        return tid

    def _pick_address(self, scam):
        cands = scam.get("candidates") or []
        named = [a for a in intake.addresses(scam.get("note", "")) if a in cands]
        if named:
            return named[0]
        if len(cands) <= 1:
            return cands[0] if cands else None
        crit = {f"a{i}": f"Write to {a}" for i, a in enumerate(cands[:8])}
        a = self.jev.ask(f"Subject: {scam['subject']}\nFrom: {scam.get('from_addr')}\n"
                         f"Reply-To: {scam.get('reply_to')}\n\n{scam['body'][:5000]}",
                         {"where": choice("Which email address does the sender want the reader to write to?", crit)})
        key, _ = picked(a, "where", "a0")
        try:
            return cands[int(key[1:])]
        except (ValueError, IndexError, TypeError):
            return cands[0]

    # ------------------------------------------------------------ owner says yes / no / hide
    def _owner_command(self, msg, thread):
        text = msg.get("extracted_text") or msg.get("text") or ""
        a = self.jev.ask(text[:3000], {"command": choice("What does the owner want Uncle to do?", OWNER_COMMANDS)})
        cmd, conf = picked(a, "command", "other")
        tid = thread["id"]
        if cmd == "approve" and conf >= 0.6 and thread["status"] == "pending_approval":
            if self.store.uncle_letters_since(time.time() - DAY) >= self.cfg.max_letters_day:
                self._tell_owner(msg, "I've written all the letters I'm allowed today. I'll send it tomorrow.\n\nVern")
                return tid
            if thread["origin_message_id"]:
                # The scammer wrote to Uncle first: answer in their own thread.
                res = self._answer(thread["origin_message_id"], thread["scammer_addr"], thread["scam_subject"],
                                   thread["draft"])
            else:
                res = self.mail.send(self.cfg.inbox, thread["scammer_addr"],
                                     "Re: " + (thread["scam_subject"] or "your letter")[:150], thread["draft"])
            now = time.time()
            self.store.update_thread(tid, status="active", approved_at=now,
                                     am_thread_id=res.get("thread_id") or thread["am_thread_id"])
            self.store.add_letter(tid, "uncle", res.get("message_id"), thread["draft"], redact.private(thread["draft"]),
                                  sent_at=now)
            self.store.note("The boss said yes. First letter's in the mail. Now I wait.", tid)
            otid = self._tell_owner(msg, f"Sent. I'll tell you when they bite. You can watch here: "
                                         f"{self.cfg.public_url}/t/{tid}\n\nVern")
            if otid and otid != thread["owner_thread_id"]:
                self.store.update_thread(tid, owner_thread_id=otid)
        elif cmd == "decline" and thread["status"] == "pending_approval":
            self.store.update_thread(tid, status="declined", close_reason="owner said no")
            self.store.note("The boss said no to that one, so I tore up my letter.", tid)
            self._tell_owner(msg, "Righto, I won't write to them.\n\nVern")
        elif cmd == "hide":
            self.store.update_thread(tid, hidden=1)
            self.store.note("The boss asked me to keep one conversation off the page, so it's hidden.", tid,
                            public=False)
            self._tell_owner(msg, "Done, that one's off the page.\n\nVern")
        else:
            self._tell_owner(msg, "I didn't quite follow. Say \"yes\" to send my letter, \"no\" to drop it, or "
                                  "\"hide\" to keep it off the page.\n\nVern")
        return tid

    # ------------------------------------------------------------ a scammer writes back
    def _scammer_letter(self, msg, thread):
        tid = thread["id"]
        text = msg.get("extracted_text") or msg.get("text") or intake.strip_html(msg.get("html") or "")
        name, _ = addr_of(msg.get("from"))
        letters = self.store.letters(tid)
        last_uncle = next((l["body"] for l in reversed(letters) if l["direction"] == "uncle"), "")
        a = self.jev.ask({"original_email": (thread["scam_text"] or "")[:2500],
                          "uncle_last_letter": last_uncle[:3000], "their_reply": text[:5000]}, {
            "is_scam": noul("Is the sender of their_reply still trying to get money, codes, details or access "
                            "from Uncle under false pretenses?"),
            "still_hooked": noul("Does the sender of their_reply want the conversation to continue?"),
            "wants_stop": noul("Is the sender of their_reply asking to stop contact, saying they have the wrong "
                               "person, or saying they want nothing from Uncle?"),
            "asking_for": choice("What is the sender of their_reply mainly asking Uncle to do now?", ASKING_FOR),
            "frustration": score("How frustrated with Uncle is the sender of their_reply?", FRUSTRATION),
        })
        p_scam = p_yes(a, "is_scam")
        hooked = p_yes(a, "still_hooked")
        stop = p_yes(a, "wants_stop")
        ask, _ = picked(a, "asking_for", "nothing_yet")
        fr = scored(a, "frustration")
        now = time.time()
        first = thread["first_bite_at"] is None
        self.store.add_letter(tid, "scammer", msg["message_id"], text,
                              redact.redact(text, names=[n for n in (name, thread["scammer_name"]) if n]),
                              jev={"is_scam": p_scam, "still_hooked": hooked, "wants_stop": stop,
                                   "asking_for": ask, "frustration": fr}, sent_at=now)
        self.store.update_thread(tid, last_scammer_at=now, frustration=fr, asking_for=ask, hooked=hooked,
                                 first_bite_at=thread["first_bite_at"] or now)
        if thread["status"] != "active":
            self.store.note("A letter came in on a closed conversation. I read it and kept quiet.", tid)
            return tid
        # A short "why are you wasting my time" can look harmless on its own, so the bar to
        # stop on "not a scam" is low; a request to stop is always honored.
        if stop >= 0.6 or p_scam < 0.3:
            reason = "they asked to stop" if stop >= 0.6 else f"{self.jev.name} now puts it at only {pct(p_scam)} scam"
            self.store.update_thread(tid, status="closed", close_reason=reason)
            self.store.note(f"Stopped writing: {reason}. Uncle doesn't pester real people.", tid)
            return tid
        if self.store.uncle_letters_since(now - DAY, tid) >= self.cfg.max_letters_per_thread_day or \
                self.store.uncle_letters_since(now - DAY) >= self.cfg.max_letters_day:
            self.store.note("They wrote again, but I've done my letters for today. They can wait.", tid)
            return tid
        history = [(l["direction"], l["body"]) for l in self.store.letters(tid)]
        letter, problems = persona.write_letter(self.llm, persona.reply_messages(
            history, ask, fr, pen_pals=self._pen_pals(exclude=tid)))
        _, writer = addr_of(msg.get("from"))
        res = self._answer(msg["message_id"], writer or thread["scammer_addr"],
                           msg.get("subject") or thread["scam_subject"], letter)
        if res.get("thread_id") and res["thread_id"] != thread["am_thread_id"]:
            self.store.update_thread(tid, am_thread_id=res["thread_id"])
        self.store.add_letter(tid, "uncle", res.get("message_id"), letter, redact.private(letter), sent_at=time.time())
        bite = "They bit! " if first else ""
        self.store.note(
            f"{bite}Letter from the scammer. {self.jev.name}: {pct(p_scam)} still a scam, {pct(hooked)} still hooked, "
            f"asking for {ask.replace('_', ' ')}, frustration {fr:.1f} of 4. Wrote back.", tid)
        if problems:
            self.store.note(f"Rewrote a draft that broke a rule ({', '.join(sorted(set(problems)))}).", tid,
                            public=False)
        if first and thread["owner_message_id"] and self.cfg.owner_emails:
            self._tell_owner({"message_id": thread["owner_message_id"], "thread_id": thread["owner_thread_id"],
                              "from": self.cfg.owner_emails[0], "subject": "They bit"},
                             f"They bit! The scammer wrote back. Watch it unfold: {self.cfg.public_url}/t/{tid}"
                             "\n\nVern")
        return tid

    def _pen_pals(self, exclude=None):
        """Uncle's other conversations, as gossip-safe (kind, how it stands) pairs for the letter prompt."""
        rows = self.store.q("SELECT id, scam_type, status, close_reason, first_bite_at FROM threads "
                            "WHERE approved_at IS NOT NULL ORDER BY id DESC LIMIT 6")
        others = []
        for t in rows:
            if t["id"] == exclude:
                continue
            if t["status"] == "closed":
                how = "their mailbox got shut down" if "bounced" in (t["close_reason"] or "") else "stopped writing"
            else:
                how = "still writing to me" if t["first_bite_at"] else "hasn't written back yet"
            others.append((t["scam_type"], how))
        return persona.pen_pals_text(others)

    def _bounce(self, msg):
        """A mail server says a letter couldn't be delivered: the scammer's mailbox is gone."""
        text = msg.get("text") or msg.get("extracted_text") or intake.strip_html(msg.get("html") or "")
        failed = set(intake.addresses(text))
        for t in self.store.active_threads():
            if (t["scammer_addr"] or "").lower() in failed:
                self.store.update_thread(t["id"], status="closed", close_reason="their address bounced")
                self.store.note("My letter came back marked undeliverable. Somebody shut their mailbox down "
                                "before I got going. Shame, I had a lot to say.", t["id"])
                if self.cfg.owner_emails:
                    self._tell_owner({"message_id": t["owner_message_id"], "thread_id": t["owner_thread_id"],
                                      "from": self.cfg.owner_emails[0], "subject": "Undeliverable"},
                                     f"My letter to {t['scammer_addr']} bounced. Their mail service has shut "
                                     "that address down, so that one's over. Send me another!\n\nVern")
                return t["id"]
        return None

    def _answer(self, message_id, to, subject, text):
        """Reply in a thread. The Fly AgentMail connector refuses message ids containing '=' (most
        Gmail ones), so when it does, send a fresh 'Re:' email to the same person instead."""
        try:
            return self.mail.reply(self.cfg.inbox, message_id, text) or {}
        except net.HttpError as exc:
            if exc.status != 403:
                raise
        subject = subject or "your letter"
        subject = subject if subject.lower().startswith("re:") else "Re: " + subject
        return self.mail.send(self.cfg.inbox, to, subject[:150], text) or {}

    # ------------------------------------------------------------ someone writes to Uncle first
    def _stranger(self, msg, sender):
        text = msg.get("extracted_text") or msg.get("text") or intake.strip_html(msg.get("html") or "")
        labels = [l.lower() for l in (msg.get("labels") or [])]
        if "spam" in labels or "unauthenticated" in labels:
            self.store.note("Mail from a sender the post office couldn't vouch for. Didn't open it.", public=False)
            return None
        a = self.jev.ask(f"Subject: {msg.get('subject', '')}\n\n{text[:6000]}", {
            "is_scam": noul("Is this email a scam or fraud attempt: trying to get money, gift cards, crypto, "
                            "personal or banking details, or remote access from the reader under false pretenses?"),
            "scam_type": choice("What kind of email is this?", SCAM_TYPES),
        })
        p = p_yes(a, "is_scam")
        kind, _ = picked(a, "scam_type", "other")
        if p < self.cfg.stranger_threshold or not self.cfg.owner_emails:
            self.store.note(f"A letter from someone new. {self.jev.name}: {pct(p)} scam, so I didn't answer.", public=True)
            return None
        name, _ = addr_of(msg.get("from"))
        letter, _ = persona.write_letter(self.llm, persona.opening_messages(msg.get("subject", ""), text,
                                                                            pen_pals=self._pen_pals()))
        tid = self.store.new_thread(
            status="pending_approval", scammer_addr=sender, scammer_name=name, scam_subject=msg.get("subject", ""),
            scam_text=text[:20000], scam_type=kind, scam_prob=p, draft=letter, am_thread_id=msg.get("thread_id"),
            origin_message_id=msg["message_id"])
        self.store.add_letter(tid, "scammer", msg["message_id"], text, redact.redact(text, names=[name] if name else []))
        self.store.note(f"A {kind.replace('_', ' ')} scam wrote to me directly ({pct(p)}). Asked the boss first.", tid)
        owner = self.cfg.owner_emails[0]
        res = self.mail.send(self.cfg.inbox, owner, f"A scammer wrote to me: {msg.get('subject', '')}"[:150], (
            f"Someone wrote to me directly. {self.jev.name} says {pct(p)} it's {kind_a(kind)} scam.\n\n"
            f"From: {sender}\n\nHere's what I'd write back:\n\n{letter}\n\n"
            "Reply \"yes\" to send it, or \"no\".\n\nVern"))
        self.store.update_thread(tid, owner_thread_id=res.get("thread_id"), owner_message_id=res.get("message_id"))
        return tid

    def _tell_owner(self, msg, text):
        """Answer the boss in their own thread, or failing that in a fresh email.

        Returns the AgentMail thread id their answer will arrive in (None if nothing got through)."""
        try:
            res = self.mail.reply(self.cfg.inbox, msg["message_id"], text)
            return (res or {}).get("thread_id") or msg.get("thread_id")
        except Exception as exc:  # noqa: BLE001
            first = exc
        _, owner = addr_of(msg.get("from"))
        subject = msg.get("subject") or "your letter"
        subject = subject if subject.lower().startswith("re:") else "Re: " + subject
        try:
            res = self.mail.send(self.cfg.inbox, owner or self.cfg.owner_emails[0], subject[:150], text)
            self.store.note(f"Replying in the boss's thread failed ({_err(first)}), so I wrote a fresh email.",
                            kind="error", public=False)
            return (res or {}).get("thread_id")
        except Exception as exc:  # noqa: BLE001
            self.store.note(f"Couldn't write back to the boss ({_err(first)}; then {_err(exc)}).", kind="error",
                            public=False)
            return None

    def _ask_approval(self, msg, tid, kind, p, to, letter):
        otid = self._tell_owner(msg, (
            f"This one's {kind_a(kind)} scam. {self.jev.name} puts it at {pct(p)}.\n\n"
            f"I'd like to write to: {to}\n\n"
            "Here's my letter:\n\n"
            f"{letter}\n\n"
            "Reply \"yes\" and I'll send it. Reply \"no\" and I'll leave them be.\n\nVern"))
        if otid and otid != msg.get("thread_id"):
            self.store.update_thread(tid, owner_thread_id=otid)
        return otid

    def resend_approval(self, tid):
        """Ask the boss again about a draft whose first ask never reached them."""
        t = self.store.thread(tid)
        if not t or t["status"] != "pending_approval":
            return "not waiting for approval"
        msg = self.mail.get_message(self.cfg.inbox, t["owner_message_id"], t["owner_thread_id"])
        otid = self._ask_approval(msg, tid, t["scam_type"], t["scam_prob"], t["scammer_addr"], t["draft"])
        return f"sent; the boss's answer will arrive in thread {otid}" if otid else "failed again, see the diary"

    # ------------------------------------------------------------ the public "try Uncle" box
    def try_uncle(self, text, ip):
        text = (text or "").strip()
        if len(text) < 30:
            return {"error": "Paste a bit more of the scam, at least a sentence or two."}
        if len(text) > 4000:
            text = text[:4000]
        now = time.time()
        h = ip_hash(ip)
        mine = self.store.one("SELECT COUNT(*) n FROM tries WHERE ip_hash=? AND at>=?", (h, now - 3600))["n"]
        total = self.store.one("SELECT COUNT(*) n FROM tries WHERE at>=?", (now - DAY,))["n"]
        if mine >= self.cfg.try_per_ip_hour:
            return {"error": "Uncle needs a nap. Try again in an hour."}
        if total >= self.cfg.try_per_day:
            return {"error": "Uncle has written all the practice letters he can today. Come back tomorrow."}
        self.store.run("INSERT INTO tries(ip_hash, at) VALUES(?,?)", (h, now))
        a = self.jev.ask(text, {
            "is_scam": noul("Is this email a scam or fraud attempt: trying to get money, gift cards, crypto, "
                            "personal or banking details, or remote access from the reader under false pretenses?"),
            "scam_type": choice("What kind of email is this?", SCAM_TYPES),
        })
        p = p_yes(a, "is_scam")
        kind, _ = picked(a, "scam_type", "other")
        if p < 0.5:
            return {"scam_prob": p, "scam_type": kind, "decider": self.jev.name,
                    "letter": None, "note": f"{self.jev.name} thinks this is only {pct(p)} likely to be a scam. Uncle only "
                                            "writes to scammers, so he's sitting this one out."}
        letter, _ = persona.write_letter(self.llm, persona.opening_messages("", text, pen_pals=self._pen_pals()))
        return {"scam_prob": p, "scam_type": kind, "decider": self.jev.name, "letter": letter,
                "note": "A practice letter. Nothing was sent to anyone."}


def jev_of(letter_row):
    try:
        return json.loads(letter_row.get("jev") or "{}")
    except (TypeError, ValueError):
        return {}
