"""What Uncle does with each email that lands in his inbox.

Every decision is a Jev question with a number attached, and every action is
written to Uncle's diary in plain words, so anyone can see why he did it.
"""
import concurrent.futures
import datetime
import email.utils
import hashlib
import json
import re
import threading
import time
import traceback

from . import intake, net, persona, redact, websearch
from .clients import choice, listed, listing, noul, p_yes, picked, score, scored

DAY = 86400

RED_FLAGS = ("If this is a scam, the red flags a careful grandparent should notice: two to four short phrases in "
             "plain words, at most 12 words each, each naming one concrete thing this email does (for example "
             "\"asks for a fee before you get paid\" or \"a stranger says you're owed millions\"). Never quote names, "
             "email addresses, phone numbers, amounts or links. Leave it empty if this isn't a scam.")
QUOTE = ("One sentence to search the web for: 8 to 14 words copied exactly, word for word, from the story the email "
         "tells (not its greeting or sign-off), with no email address, phone number or link in it.")


def loads(s, default=None):
    try:
        return json.loads(s) if s else default
    except (TypeError, ValueError):
        return default

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


# How the page says each ask, in plain words.
ASK_WORDS = {
    "money_transfer": "wire money", "gift_cards": "buy gift cards", "crypto": "send crypto", "fee": "pay a fee",
    "personal_details": "hand over his details", "move_chat": "move to WhatsApp or a call",
    "click_or_install": "click a link", "nothing_yet": "keep talking (no ask yet)",
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


LIMIT_AT = re.compile(r"\bat (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)")


def mail_limit(exc, now=None):
    """AgentMail lets a brand-new account write to only so many different people (10 on day one, 25 in week
    one). When that stops a letter, the time it's worth trying again; None for any other error."""
    if not isinstance(exc, net.HttpError) or exc.status != 429 or "recipient limit" not in (exc.body or "").lower():
        return None
    now = now or time.time()
    times = []
    for stamp in LIMIT_AT.findall(exc.body):
        try:
            times.append(datetime.datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp())
        except ValueError:
            pass
    later = [t for t in times if t > now]
    return min(later) if later else now + 3600


def when_text(ts, now=None):
    """'after 07:32 UTC on Nov 28, about 9 hours from now'"""
    h = max(0.0, (ts - (now or time.time())) / 3600)
    if h < 0.75:
        about = "within the hour"
    elif h < 36:
        about = f"about {round(h)} hour{'' if round(h) == 1 else 's'} from now"
    else:
        about = f"about {round(h / 24)} days from now"
    g = time.gmtime(ts)
    return f"after {time.strftime('%H:%M', g)} UTC on {time.strftime('%b', g)} {g.tm_mday}, {about}"


def _err(exc):
    """'HttpError 403: {"error": ...}' for the private diary."""
    return f"{exc.__class__.__name__} {getattr(exc, 'status', '')}: {str(getattr(exc, 'body', '') or exc)[:160]}"


def kind_a(kind):
    """'an advance fee', 'a romance'."""
    words = {"probe": "address-check"}.get(kind, (kind or "other").replace("_", " "))
    return ("an " if words[0] in "aeiou" else "a ") + words


class Engine:
    def __init__(self, cfg, store, mail, jev, llm, memory=None, web=None):
        self.cfg = cfg
        self.store = store
        self.mail = mail
        self.jev = jev
        self.llm = llm
        self.memory = memory
        self.web = web
        self.lock = threading.Lock()
        # Web searches run beside letter writing; one that outlasts its wait still finishes and is remembered.
        self.pool = concurrent.futures.ThreadPoolExecutor(3, thread_name_prefix="web")

    # ------------------------------------------------------------ the verdict: why it's a scam
    def _questions(self, base):
        """Add red flags and a sentence to search for, when the decider can answer lists (Claude can)."""
        if getattr(self.jev, "lists", False):
            return dict(base, red_flags=listing(RED_FLAGS, 4), quote=listing(QUOTE, 1))
        return base

    @staticmethod
    def _flags(a):
        return [f.rstrip(". ") for f in listed(a, "red_flags")][:4]

    def _look_up(self, a, text, wait=60):
        """Start searching the web for one sentence of this scam: (phrase, future). The future is None when
        Uncle can't look right now; the phrase is kept so a later round can look instead."""
        phrase = websearch.good_quote((listed(a, "quote") or [""])[0], text)
        if not phrase or not self.web or not self.web.available():
            return phrase, None
        return phrase, self.pool.submit(self.web.check, phrase, wait)

    def _web_result(self, searching, timeout=45):
        """What the search found, or just {"phrase"} when it isn't back yet (a later round fills it in)."""
        phrase, future = searching
        if not phrase:
            return None
        if future:
            try:
                res = future.result(timeout=timeout)
                if res:
                    return res
            except Exception as exc:  # noqa: BLE001  (a nicety: nothing waits on it for long)
                self.store.note(f"The web search didn't come back in time ({_err(exc)}).", kind="error", public=False)
        return {"phrase": phrase}

    def _verdict(self, p, kind, flags, web):
        """'Claude puts it at 99%: an advance fee scam.' plus the red flags and what the web search found."""
        parts = [f"{self.jev.name} puts it at {pct(p)}: {kind_a(kind)} scam."]
        if flags:
            parts.append("The red flags:\n" + "\n".join(f"- {f}" for f in flags))
        line = websearch.web_line(web, self.web.name if self.web else "Apify")
        if line:
            parts.append(line)
        return "\n\n".join(parts)

    def fill_in(self, limit=3):
        """Red flags and a web search for conversations from before Uncle gave verdicts. Returns how many."""
        n = 0
        rows = self.store.q("SELECT id, scam_subject, scam_text, flags, web FROM threads WHERE status IN "
                            "('pending_approval','active','closed') AND scam_text IS NOT NULL AND scam_text != '' "
                            "AND flags IS NULL AND ? ORDER BY id LIMIT ?",
                            (1 if getattr(self.jev, "lists", False) else 0, limit))
        for t in rows:
            a = self.jev.ask(intake_state(t["scam_subject"], t["scam_text"]), self._questions({}))
            phrase = websearch.good_quote((listed(a, "quote") or [""])[0], t["scam_text"])
            self.store.update_thread(t["id"], flags=json.dumps(self._flags(a)),
                                     web=t["web"] or (json.dumps({"phrase": phrase}) if phrase else None))
            n += 1
        if self.web and self.web.available():
            for t in self.store.q("SELECT id, web FROM threads WHERE web IS NOT NULL AND web NOT LIKE '%\"at\"%' "
                                  "ORDER BY id LIMIT ?", (limit,)):
                phrase = (loads(t["web"], {}) or {}).get("phrase")
                if not phrase:
                    self.store.update_thread(t["id"], web=None)
                    continue
                try:
                    res = self.web.check(phrase, wait=90)
                except Exception as exc:  # noqa: BLE001  (try again next round)
                    self.store.note(f"{self.web.name} couldn't search the web ({_err(exc)}).", kind="error",
                                    public=False)
                    break
                if res is None:
                    break  # today's searches are used up
                self.store.update_thread(t["id"], web=json.dumps(res))
                n += 1
        return n

    # ------------------------------------------------------------ memory for scripts
    def _remember(self, tid):
        """Has Uncle had this script before? [(thread id, score)], [] when he can't tell."""
        if not self.memory:
            return []
        try:
            kin = self.memory.remember(tid) or []
        except Exception as exc:  # noqa: BLE001  (memory is a nicety; a letter never waits on it)
            self.store.note(f"Couldn't ask {self.memory.name} about this one ({_err(exc)}).", tid, kind="error",
                            public=False)
            return []
        if kin:
            others = ", ".join(f"#{k}" for k, _ in kin)
            self.store.note(f"{self.memory.name} says I've had this letter before: same script as {others}, "
                            f"{pct(kin[0][1])} alike.", tid)
        return kin

    def _kin_line(self, kin):
        if not kin:
            return ""
        best, s = kin[0]
        t = self.store.thread(best) or {}
        reason = t.get("close_reason") or ""
        how = {"active": f"which I'm writing to at {t.get('scammer_addr')}",
               "pending_approval": "which is waiting on your yes",
               "closed": (f"whose address ({t.get('scammer_addr')}) bounced" if "bounced" in reason
                          else f"which is over ({reason or 'closed'})")}.get(t.get("status"), "which we passed on")
        return (f"{self.memory.name} remembers this script: it's {pct(s)} like #{best} "
                f"(\"{(t.get('scam_subject') or '')[:60]}\"), {how}. A new address on an old script is how they "
                "keep going after a mailbox gets shut down.\n\n")

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
                    or self.store.active_by_scammer(sender) or intake.looks_forwarded(msg)
                    or self._practice_for(msg, sender)):
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
                when = mail_limit(exc)
                if when:
                    self.store.put("mail_blocked_until", when)
                    self.store.finish_message(message_id, "waiting", status="waiting", detail=f"mail limit {when}")
                    self.store.note(f"My mailbox is too new to write to anyone else yet, so this one waits until "
                                    f"{when_text(when)}.", kind="error", public=False)
                    return "waiting"
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
            if known and (known["status"] == "done"
                          or (known["status"] == "processing" and (known["created_at"] or 0) > time.time() - 900)
                          or (known["status"] == "waiting" and time.time() < self.mail_blocked_until())):
                continue
            if self.handle(mid) not in ("self", "duplicate"):
                n += 1
        return n

    def rounds(self):
        """Uncle's mailbox check, whenever something wakes him: pick up missed mail, then follow up once on
        any first letter that has gone a day without an answer."""
        out = {"caught_up": self.catch_up(), "nudged": self.nudge_due()}
        try:
            out["sent_waiting"] = self.send_waiting()
        except Exception as exc:  # noqa: BLE001
            self.store.note(f"Couldn't send a waiting letter ({_err(exc)}).", kind="error", public=False)
        if self.memory:
            try:
                out["remembered"] = self.memory.backfill()
            except Exception as exc:  # noqa: BLE001
                self.store.note(f"Couldn't fill in {self.memory.name}'s memory ({_err(exc)}).", kind="error",
                                public=False)
        try:
            out["verdicts"] = self.fill_in()
        except Exception as exc:  # noqa: BLE001
            self.store.note(f"Couldn't fill in red flags or web searches ({_err(exc)}).", kind="error", public=False)
        return out

    def mail_blocked_until(self):
        try:
            return float(self.store.get("mail_blocked_until") or 0)
        except ValueError:
            return 0.0

    def send_waiting(self, now=None):
        """First letters the boss said yes to while the mail limit was on: send them once it lifts."""
        now = now or time.time()
        sent = 0
        with self.lock:
            for t in self.store.q("SELECT * FROM threads WHERE status='pending_approval' AND send_after IS NOT NULL "
                                  "AND send_after<=? ORDER BY id", (now,)):
                if self.store.uncle_letters_since(now - DAY) >= self.cfg.max_letters_day:
                    break
                try:
                    self._send_first(t)
                except net.HttpError as exc:
                    when = mail_limit(exc, now)
                    if not when:
                        raise
                    self.store.put("mail_blocked_until", when)
                    self.store.run("UPDATE threads SET send_after=? WHERE status='pending_approval' "
                                   "AND send_after IS NOT NULL AND send_after<?", (when, when))
                    break
                sent += 1
                if self.cfg.owner_emails and t["owner_message_id"]:
                    otid = self._tell_owner(
                        {"message_id": t["owner_message_id"], "thread_id": t["owner_thread_id"],
                         "from": self.cfg.owner_emails[0], "subject": "Sent"},
                        f"The letter to {t['scammer_addr']} that was waiting on the mail limit just went out. You "
                        f"can watch here: {self.cfg.public_url}/t/{t['id']}\n\nVern")
                    if otid and otid != t["owner_thread_id"]:
                        self.store.update_thread(t["id"], owner_thread_id=otid)
        return sent

    def _send_first(self, thread):
        """Uncle's first letter to a scammer the boss said yes to."""
        tid = thread["id"]
        if thread["origin_message_id"]:
            # The scammer wrote to Uncle first: answer in their own thread.
            res = self._answer(thread["origin_message_id"], thread["scammer_addr"], thread["scam_subject"],
                               thread["draft"])
        else:
            res = self.mail.send(self.cfg.inbox, thread["scammer_addr"],
                                 "Re: " + (thread["scam_subject"] or "your letter")[:150], thread["draft"])
        now = time.time()
        self.store.update_thread(tid, status="active", approved_at=now, send_after=None,
                                 am_thread_id=res.get("thread_id") or thread["am_thread_id"])
        self.store.add_letter(tid, "uncle", res.get("message_id"), thread["draft"], redact.private(thread["draft"]),
                              sent_at=now)
        self.store.note("The boss said yes. First letter's in the mail. Now I wait.", tid)
        return res

    def nudge_due(self, now=None):
        with self.lock:
            return self._nudge_due(now or time.time())

    def _nudge_due(self, now):
        sent = 0
        for t in self.store.active_threads():
            letters = self.store.letters(t["id"])
            uncle = [l for l in letters if l["direction"] == "uncle"]
            if len(uncle) != 1 or any(l["direction"] == "scammer" for l in letters) or t["origin_message_id"]:
                continue  # they've written, or he's already followed up
            if (uncle[0]["sent_at"] or now) > now - self.cfg.nudge_after_hours * 3600:
                continue
            if self.store.uncle_letters_since(now - DAY) >= self.cfg.max_letters_day:
                break
            letter, _ = persona.write_letter(self.llm, persona.nudge_messages(
                t["scam_subject"], t["scam_text"], uncle[0]["body"]))
            res = self.mail.send(self.cfg.inbox, t["scammer_addr"],
                                 "Re: " + (t["scam_subject"] or "my letter")[:150], letter) or {}
            self.store.add_letter(t["id"], "uncle", res.get("message_id"), letter, redact.private(letter),
                                  sent_at=time.time())
            self.store.note("Not a peep in a day, so I sent a short note to make sure my letter got there.", t["id"])
            sent += 1
        return sent

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
        prac = self._practice_for(msg, sender)
        if prac:
            return "practice", self._practice_reply(msg, prac, sender)
        if intake.looks_forwarded(msg):
            return "visitor", self._visitor(msg, sender)
        return "stranger", self._stranger(msg, sender)

    # ------------------------------------------------------------ owner forwards a scam
    def _intake(self, msg):
        exclude = set(self.cfg.owner_emails) | {self.cfg.inbox}
        scam = intake.extract_scam(
            msg, lambda att: self.mail.get_attachment(self.cfg.inbox, msg["message_id"], att), exclude)
        scam = scam or intake.pasted(msg, exclude)
        if scam is None:
            self._tell_owner(msg, "I couldn't find a forwarded email in that one. Open the scam itself, press plain "
                                  "Forward (not \"as attachment\") and send it to me. Or paste it into a new email: "
                                  "their email address alone on the first line, the scam below.\n\nVern")
            self.store.note("Got a note from the boss with no scam inside, so I asked for the real thing.")
            return None
        a = self.jev.ask(intake_state(scam["subject"], scam["body"]), self._questions(intake_questions()))
        p = p_yes(a, "is_scam")
        p_reply = p_yes(a, "wants_email_reply")
        kind, _ = picked(a, "scam_type", "other")
        to = self._pick_address(scam)
        base = dict(scammer_addr=to or "", scammer_name=scam.get("from_name", ""), scam_subject=scam["subject"],
                    scam_text=scam["body"][:20000], scam_type=kind, scam_prob=p,
                    owner_thread_id=msg.get("thread_id"), owner_message_id=msg["message_id"],
                    flags=json.dumps(self._flags(a)))
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
        # One sender often blasts the same scam many times, sometimes with the same reply-to.
        seen = self.store.one("SELECT id, status, close_reason FROM threads WHERE scammer_addr=? AND status IN "
                              "('pending_approval','active','closed') ORDER BY id DESC", (to,))
        if seen:
            if seen["status"] == "closed":
                why = seen["close_reason"] or "that conversation is over"
                self._tell_owner(msg, f"I already tried {to}, and {why}. If the email has a different reply-to "
                                      "address, put that one on the first line and send it again.\n\nVern")
            else:
                self._tell_owner(msg, f"I'm already writing to {to}, so one letter's enough. You can watch here: "
                                      f"{self.cfg.public_url}/t/{seen['id']}\n\nVern")
            return seen["id"]
        if len(self.store.active_threads()) >= self.cfg.max_active_threads:
            tid = self.store.new_thread(status="rejected", close_reason="too many open conversations", **base)
            self._tell_owner(msg, "My plate's full right now. I'll take this one when a pen pal gives up.\n\nVern")
            return tid
        searching = self._look_up(a, scam["body"])
        letter, problems = persona.write_letter(self.llm, persona.opening_messages(
            scam["subject"], scam["body"], pen_pals=self._pen_pals()))
        web = self._web_result(searching)
        tid = self.store.new_thread(status="pending_approval", draft=letter, web=json.dumps(web) if web else None,
                                    **base)
        self.store.note(
            f"New one from the boss: {kind_a(kind)} scam. {self.jev.name}: {pct(p)} scam, {pct(p_reply)} wants an "
            f"email back. Drafted my first letter and asked the boss before sending.", tid)
        if problems:
            self.store.note(f"My first draft broke a rule ({', '.join(sorted(set(problems)))}), so I rewrote it.",
                            tid, public=False)
        self._ask_approval(msg, tid, kind, p, to, letter, extra=self._kin_line(self._remember(tid)))
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
            if thread.get("send_after"):
                self._tell_owner(msg, f"Already on it: that letter goes out by itself {when_text(thread['send_after'])}."
                                      "\n\nVern")
                return tid
            if self.store.uncle_letters_since(time.time() - DAY) >= self.cfg.max_letters_day:
                self._tell_owner(msg, "I've written all the letters I'm allowed today. I'll send it tomorrow.\n\nVern")
                return tid
            try:
                self._send_first(thread)
            except net.HttpError as exc:
                when = mail_limit(exc)
                if not when:
                    raise
                self.store.put("mail_blocked_until", when)
                self.store.update_thread(tid, send_after=when)
                self.store.note("The boss said yes, but my mailbox is too new to write to anyone else just yet. "
                                "The letter goes out as soon as the post office lets me.", tid)
                self._tell_owner(msg, (
                    "Got your yes. But my mailbox is brand new, and AgentMail only lets a new one write to a few "
                    "different people at first (10 on the first day, 25 in the first week). So this letter waits, "
                    f"and I'll send it myself {when_text(when)}. I'll tell you when it's gone.\n\nVern"))
                return tid
            otid = self._tell_owner(msg, f"Sent. I'll tell you when they bite. You can watch here: "
                                         f"{self.cfg.public_url}/t/{tid}\n\nVern")
            if otid and otid != thread["owner_thread_id"]:
                self.store.update_thread(tid, owner_thread_id=otid)
        elif cmd == "decline" and thread["status"] == "pending_approval":
            self.store.update_thread(tid, status="declined", close_reason="owner said no", send_after=None)
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
        p_scam, hooked, stop, ask, fr = self._read_reply(thread["scam_text"], last_uncle, text)
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

    def _read_reply(self, original, last_uncle, reply):
        """What the decision model makes of a scammer's reply: (is_scam, still_hooked, wants_stop, asking_for,
        frustration)."""
        a = self.jev.ask({"original_email": (original or "")[:2500],
                          "uncle_last_letter": (last_uncle or "")[:3000], "their_reply": (reply or "")[:5000]}, {
            "is_scam": noul("Is the sender of their_reply still trying to get money, codes, details or access "
                            "from Uncle under false pretenses?"),
            "still_hooked": noul("Does the sender of their_reply want the conversation to continue?"),
            "wants_stop": noul("Is the sender of their_reply asking to stop contact, saying they have the wrong "
                               "person, or saying they want nothing from Uncle?"),
            "asking_for": choice("What is the sender of their_reply mainly asking Uncle to do now?", ASKING_FOR),
            "frustration": score("How frustrated with Uncle is the sender of their_reply?", FRUSTRATION),
        })
        ask, _ = picked(a, "asking_for", "nothing_yet")
        return p_yes(a, "is_scam"), p_yes(a, "still_hooked"), p_yes(a, "wants_stop"), ask, scored(a, "frustration")

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

    # ------------------------------------------------------------ anyone else forwards him a scam
    def _visitor(self, msg, sender):
        """Someone who isn't the boss forwards a scam, a judge say. They get the letter Uncle would
        write, by email, in a minute. Nothing goes to the scammer: only the boss picks real pen pals."""
        labels = [l.lower() for l in (msg.get("labels") or [])]
        if "unauthenticated" in labels or not sender:
            self.store.note("A forward from a sender the post office couldn't vouch for. Didn't answer.", public=False)
            return None
        now = time.time()
        h = ip_hash("mail:" + sender)
        mine = self.store.one("SELECT COUNT(*) n FROM tries WHERE ip_hash=? AND at>=?", (h, now - DAY))["n"]
        total = self.store.one("SELECT COUNT(*) n FROM tries WHERE at>=?", (now - DAY,))["n"]
        if mine >= self.cfg.visitor_per_day or total >= self.cfg.try_per_day:
            self.store.note("A forward from someone over today's practice-letter limit. Let it be.", public=False)
            return None
        self.store.run("INSERT INTO tries(ip_hash, at) VALUES(?,?)", (h, now))
        subject = msg.get("subject") or "your letter"
        scam = intake.extract_scam(
            msg, lambda att: self.mail.get_attachment(self.cfg.inbox, msg["message_id"], att),
            {sender, self.cfg.inbox, *self.cfg.owner_emails})
        if scam and (scam.get("from_addr") or "").lower() == sender:
            # "Forwarding" their own pitch is a scammer's trick, not a visitor. The boss decides.
            return self._stranger(msg, sender)
        if scam is None:
            self._answer(msg["message_id"], sender, subject, (
                "Thanks for writing! I couldn't find the scam in there, though. Open it, press plain Forward "
                "(not \"as attachment\") and send it to me, and I'll show you what I'd write back.\n\nVern"))
            return None
        a = self.jev.ask(f"Subject: {scam['subject']}\n\n{scam['body'][:6000]}", self._questions({
            "is_scam": noul("Is this email a scam or fraud attempt: trying to get money, gift cards, crypto, "
                            "personal or banking details, or remote access from the reader under false pretenses?"),
            "scam_type": choice("What kind of email is this?", SCAM_TYPES),
        }))
        p = p_yes(a, "is_scam")
        kind, _ = picked(a, "scam_type", "other")
        if p < self.cfg.scam_threshold:
            self._answer(msg["message_id"], sender, subject, (
                f"Thanks for sending this over! {self.jev.name} says it's only {pct(p)} likely to be a scam, so "
                "I'll sit this one out. I only write to the real thing. Got a real stinker in your spam folder? "
                f"Forward me that one.\n\nVern\n\n{self.cfg.public_url}"))
            self.store.note(f"Someone forwarded me an email to see what I'd say. {self.jev.name}: only {pct(p)} "
                            "a scam, so I sat it out.")
            return None
        flags = self._flags(a)
        searching = self._look_up(a, scam["body"])
        letter, _ = persona.write_letter(self.llm, persona.opening_messages(
            scam["subject"], scam["body"], pen_pals=self._pen_pals()))
        web = self._web_result(searching)
        to = self._pick_address(scam)
        nominated = self._nominate(scam, to, kind, p, letter, sender, flags, web)
        later = ("I've asked my boss whether I should write to them for real. If he says yes, the conversation "
                 "goes up on my page with names, emails and numbers blacked out. ") if nominated else ""
        n = self.cfg.practice_rounds
        res = self._answer(msg["message_id"], sender, subject, (
            "Thanks for sending this one over! Yes, it's a scam.\n\n"
            f"{self._verdict(p, kind, flags, web)}\n\n"
            "Don't answer it yourself, click its links or send anything. Leave the answering to me.\n\n"
            "Here's what I'd write back to them:\n\n"
            f"------------------------------\n{letter}\n------------------------------\n\n"
            "Want to see me handle them? Reply to this email as the scammer: push me, get cross, ask for the fee. "
            f"I'll write back the way I do to the real ones, for up to {n} rounds. Each email you send wakes me "
            "up on my Fly.io Sprite, and I nod off again after.\n\n"
            f"Nothing has gone to the scammer. {later}You can read along with my real pen pals here:\n"
            f"{self.cfg.public_url}\n\nVern"))
        self.store.run("INSERT OR REPLACE INTO practice(am_thread_id, visitor, scam, turns, started_at, updated_at) "
                       "VALUES(?,?,?,?,?,?)", (res.get("thread_id") or msg.get("thread_id") or msg["message_id"],
                                               sender, scam["body"][:4000],
                                               json.dumps([{"who": "uncle", "text": letter}]), now, now))
        self.store.note(f"Someone forwarded me {kind_a(kind)} scam ({pct(p)}) to see what I'd say. I mailed them "
                        "my practice letter. Nothing went to the scammer"
                        + (" yet: I asked the boss if I should write for real." if nominated else "."), nominated)
        return nominated

    # ------------------------------------------------------------ a visitor plays the scammer by email
    def _practice_for(self, msg, sender):
        """The practice conversation this email continues, if any: by mail thread, else by sender."""
        tid = msg.get("thread_id")
        row = self.store.one("SELECT * FROM practice WHERE am_thread_id=? AND visitor=?", (tid, sender)) if tid else None
        if row or intake.looks_forwarded(msg):
            return row
        # A fresh-email fallback starts a new mail thread, so also know them by address for a couple of days.
        return self.store.one("SELECT * FROM practice WHERE visitor=? AND updated_at>=? ORDER BY updated_at DESC",
                              (sender, time.time() - 2 * DAY))

    def _practice_reply(self, msg, prac, sender):
        """The visitor writes back as the scammer, and Uncle answers by email the way he answers a real one.
        Nothing goes to any real scammer, and nothing of theirs goes on the page."""
        labels = [l.lower() for l in (msg.get("labels") or [])]
        if "unauthenticated" in labels:
            self.store.note("A practice reply the post office couldn't vouch for. Didn't answer.", public=False)
            return None
        turns = loads(prac["turns"], []) or []
        rounds = sum(1 for t in turns if t["who"] == "scammer")
        n = self.cfg.practice_rounds
        if rounds >= n:
            return None  # they've had their rounds, and the last letter said so
        now = time.time()
        h = ip_hash("practice:" + sender)
        mine = self.store.one("SELECT COUNT(*) n FROM tries WHERE ip_hash=? AND at>=?", (h, now - DAY))["n"]
        total = self.store.one("SELECT COUNT(*) n FROM tries WHERE at>=?", (now - DAY,))["n"]
        if mine >= self.cfg.visitor_per_day * n or total >= self.cfg.try_per_day:
            self.store.note("A practice reply from someone over today's limit. Let it be.", public=False)
            return None
        self.store.run("INSERT INTO tries(ip_hash, at) VALUES(?,?)", (h, now))
        text = (msg.get("extracted_text") or msg.get("text") or intake.strip_html(msg.get("html") or "")).strip()[:3000]
        subject = msg.get("subject") or "my letter"
        last_uncle = next((t["text"] for t in reversed(turns) if t["who"] == "uncle"), "")
        p_scam, hooked, stop, ask, fr = self._read_reply(prac["scam"], last_uncle, text)
        read = (f"{self.jev.name} read your letter: {pct(p_scam)} still a scam, {pct(hooked)} still hooked, mood "
                f"{fr:.1f} of 4, wants me to {ASK_WORDS.get(ask, 'do something')}.")
        turns.append({"who": "scammer", "text": text})
        if stop >= 0.6 or p_scam < 0.3:
            why = "you asked me to stop" if stop >= 0.6 else "that doesn't read like a scam any more"
            self._answer(msg["message_id"], sender, subject, (
                f"{read}\n\nI'd stop writing here, because {why}. I never pester real people.\n\n"
                f"Thanks for playing. My real pen pals are here: {self.cfg.public_url}\n\nVern"))
            turns += [{"who": "scammer", "text": ""}] * (n - rounds - 1)  # that's the end of it
        else:
            history = [("scammer", prac["scam"])] + [(t["who"], t["text"]) for t in turns]
            letter, _ = persona.write_letter(self.llm, persona.reply_messages(history, ask, fr,
                                                                              pen_pals=self._pen_pals()))
            turns.append({"who": "uncle", "text": letter})
            more = ("Reply again to keep going." if rounds + 1 < n else
                    "That was the last round. A real scammer gets to keep going as long as they like.")
            self._answer(msg["message_id"], sender, subject, (
                f"{letter}\n\n------------------------------\n"
                f"Practice, round {rounds + 1} of {n}. {read} Nothing goes to any real scammer. {more}\n"
                "Your email just woke me up on my Fly.io Sprite. Back to sleep now.\n"
                f"My real pen pals: {self.cfg.public_url}"))
        self.store.run("UPDATE practice SET turns=?, updated_at=? WHERE am_thread_id=?",
                       (json.dumps(turns), now, prac["am_thread_id"]))
        self.store.note(f"Someone is playing the scammer by email to see what I do (round {rounds + 1}). I wrote "
                        "back. Nothing went to any real scammer.")
        return None

    def _nominate(self, scam, to, kind, p, letter, sender, flags=(), web=None):
        """A forward from someone else can become a real pen pal, but only on the boss's yes, and only when the
        address is on a free mail service: a company's own domain is too often a real business or a hacked box."""
        if not to or not intake.webmail(to) or not self.cfg.owner_emails:
            return None
        if self.store.one("SELECT id FROM threads WHERE scammer_addr=?", (to,)):
            return None  # already writing to them, already asked, or they bounced
        if len(self.store.active_threads()) >= self.cfg.max_active_threads:
            return None
        tid = self.store.new_thread(
            status="pending_approval", scammer_addr=to, scammer_name=scam.get("from_name", ""),
            scam_subject=scam["subject"], scam_text=scam["body"][:20000], scam_type=kind, scam_prob=p, draft=letter,
            flags=json.dumps(list(flags)), web=json.dumps(web) if web else None)
        res = self.mail.send(self.cfg.inbox, self.cfg.owner_emails[0], f"A friend sent me a scam: {scam['subject']}"[:150], (
            f"Somebody ({sender}) forwarded me a scam.\n\n{self._verdict(p, kind, flags, web)}\n\n"
            f"I'd like to write to: {to}\n\n"
            "Only say yes if you know who sent it. A stranger could fake a forward to set me on someone "
            f"innocent.\n\n{self._kin_line(self._remember(tid))}"
            f"Here's my letter:\n\n{letter}\n\n"
            "Reply \"yes\" and I'll send it. Reply \"no\" and I'll leave them be.\n\nVern")) or {}
        self.store.update_thread(tid, owner_thread_id=res.get("thread_id"), owner_message_id=res.get("message_id"))
        return tid

    # ------------------------------------------------------------ someone writes to Uncle first
    def _stranger(self, msg, sender):
        text = msg.get("extracted_text") or msg.get("text") or intake.strip_html(msg.get("html") or "")
        labels = [l.lower() for l in (msg.get("labels") or [])]
        if "spam" in labels or "unauthenticated" in labels:
            self.store.note("Mail from a sender the post office couldn't vouch for. Didn't open it.", public=False)
            return None
        a = self.jev.ask(f"Subject: {msg.get('subject', '')}\n\n{text[:6000]}", self._questions({
            "is_scam": noul("Is this email a scam or fraud attempt: trying to get money, gift cards, crypto, "
                            "personal or banking details, or remote access from the reader under false pretenses?"),
            "scam_type": choice("What kind of email is this?", SCAM_TYPES),
        }))
        p = p_yes(a, "is_scam")
        kind, _ = picked(a, "scam_type", "other")
        if p < self.cfg.stranger_threshold or not self.cfg.owner_emails:
            self.store.note(f"A letter from someone new. {self.jev.name}: {pct(p)} scam, so I didn't answer.", public=True)
            return None
        name, _ = addr_of(msg.get("from"))
        flags = self._flags(a)
        searching = self._look_up(a, text)
        letter, _ = persona.write_letter(self.llm, persona.opening_messages(msg.get("subject", ""), text,
                                                                            pen_pals=self._pen_pals()))
        web = self._web_result(searching)
        tid = self.store.new_thread(
            status="pending_approval", scammer_addr=sender, scammer_name=name, scam_subject=msg.get("subject", ""),
            scam_text=text[:20000], scam_type=kind, scam_prob=p, draft=letter, am_thread_id=msg.get("thread_id"),
            origin_message_id=msg["message_id"], flags=json.dumps(flags), web=json.dumps(web) if web else None)
        self.store.add_letter(tid, "scammer", msg["message_id"], text, redact.redact(text, names=[name] if name else []))
        self.store.note(f"A {kind.replace('_', ' ')} scam wrote to me directly ({pct(p)}). Asked the boss first.", tid)
        owner = self.cfg.owner_emails[0]
        res = self.mail.send(self.cfg.inbox, owner, f"A scammer wrote to me: {msg.get('subject', '')}"[:150], (
            f"Someone wrote to me directly.\n\n{self._verdict(p, kind, flags, web)}\n\n"
            f"From: {sender}\n\n{self._kin_line(self._remember(tid))}Here's what I'd write back:\n\n{letter}\n\n"
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

    def _ask_approval(self, msg, tid, kind, p, to, letter, extra=""):
        domain = (to or "").rsplit("@", 1)[-1]
        careful = "" if intake.webmail(to) else (
            f"Careful: {domain} isn't a free email service. It could be a real business, or a mailbox the "
            "scammer broke into. Say yes only if you're sure it's theirs.\n\n")
        t = self.store.thread(tid) or {}
        otid = self._tell_owner(msg, (
            f"{self._verdict(p, kind, loads(t.get('flags'), []), loads(t.get('web')))}\n\n"
            f"I'd like to write to: {to}\n\n{careful}{extra}"
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
    def _try_slot(self, ip):
        """Count one practice turn against the per-visitor and daily limits. Returns an error or None."""
        now = time.time()
        h = ip_hash(ip)
        mine = self.store.one("SELECT COUNT(*) n FROM tries WHERE ip_hash=? AND at>=?", (h, now - 3600))["n"]
        total = self.store.one("SELECT COUNT(*) n FROM tries WHERE at>=?", (now - DAY,))["n"]
        if mine >= self.cfg.try_per_ip_hour:
            return "Uncle needs a nap. Try again in an hour."
        if total >= self.cfg.try_per_day:
            return "Uncle has written all the practice letters he can today. Come back tomorrow."
        self.store.run("INSERT INTO tries(ip_hash, at) VALUES(?,?)", (h, now))
        return None

    def try_uncle(self, text, ip):
        text = (text or "").strip()
        if len(text) < 30:
            return {"error": "Paste a bit more of the scam, at least a sentence or two."}
        text = text[:4000]
        err = self._try_slot(ip)
        if err:
            return {"error": err}
        # The decision and the letter at once, so a visitor waits for one model call, not two.
        # A letter written for something that turns out not to be a scam is simply thrown away.
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            decided = pool.submit(self.jev.ask, text, self._questions({
                "is_scam": noul("Is this email a scam or fraud attempt: trying to get money, gift cards, crypto, "
                                "personal or banking details, or remote access from the reader under false pretenses?"),
                "scam_type": choice("What kind of email is this?", SCAM_TYPES),
            }))
            written = pool.submit(persona.write_letter, self.llm,
                                  persona.opening_messages("", text, pen_pals=self._pen_pals()))
            a = decided.result()
            p = p_yes(a, "is_scam")
            kind, _ = picked(a, "scam_type", "other")
            if p < 0.5:
                written.cancel()
                return {"scam_prob": p, "scam_type": kind, "decider": self.jev.name,
                        "letter": None, "note": f"{self.jev.name} thinks this is only {pct(p)} likely to be a scam. "
                                                "Uncle only writes to scammers, so he's sitting this one out."}
            letter, _ = written.result()
        return {"scam_prob": p, "scam_type": kind, "decider": self.jev.name, "letter": letter,
                "flags": self._flags(a), "kind": kind_a(kind),
                "note": "A practice letter. Nothing was sent to anyone."}

    def try_reply(self, scam, turns, reply, ip):
        """Practice, round two: the visitor plays the scammer and Uncle answers, the same way he answers a
        real one. Nothing is stored or sent."""
        reply = (reply or "").strip()[:3000]
        scam = (scam or "").strip()[:4000]
        if len(reply) < 5 or len(scam) < 30:
            return {"error": "Write Uncle a reply first."}
        turns = [t for t in (turns or []) if isinstance(t, dict) and t.get("who") in ("uncle", "scammer")
                 and isinstance(t.get("text"), str)][-8:]
        if not turns or len(turns) >= 8:
            return {"error": "That's as far as practice goes."}
        err = self._try_slot(ip)
        if err:
            return {"error": err}
        last_uncle = next((t["text"] for t in reversed(turns) if t["who"] == "uncle"), "")
        p_scam, hooked, stop, ask, fr = self._read_reply(scam, last_uncle, reply)
        read = (f"{self.jev.name} read your letter: {pct(p_scam)} still a scam, {pct(hooked)} still hooked, mood "
                f"{fr:.1f} of 4, wants Uncle to {ASK_WORDS.get(ask, 'do something')}.")
        if stop >= 0.6 or p_scam < 0.3:
            why = "you asked him to stop" if stop >= 0.6 else "that no longer reads like a scam"
            return {"read": read, "letter": None,
                    "note": f"Uncle stops writing here, because {why}. He never pesters real people."}
        history = [("scammer", scam)] + [(t["who"], t["text"][:4000]) for t in turns] + [("scammer", reply)]
        letter, _ = persona.write_letter(self.llm, persona.reply_messages(history, ask, fr, pen_pals=self._pen_pals()))
        return {"read": read, "letter": letter, "note": "Practice. Nothing was sent to anyone."}


def jev_of(letter_row):
    try:
        return json.loads(letter_row.get("jev") or "{}")
    except (TypeError, ValueError):
        return {}
