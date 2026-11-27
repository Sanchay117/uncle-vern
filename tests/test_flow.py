import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uncle import clients, gateway, intake, meter, persona, redact, web  # noqa: E402
from uncle.config import Config  # noqa: E402
from uncle.server import App  # noqa: E402

OWNER = "me@gmail.com"
INBOX = "uncle@agentmail.test"

GMAIL_FORWARD = """Uncle, this one's for you.

---------- Forwarded message ---------
From: Barrister James Okoro <james.okoro@outlook-mail.example>
Date: Thu, Nov 26, 2026 at 3:14 AM
Subject: URGENT: Unclaimed Inheritance Fund of USD 4.5 Million
To: <me@gmail.com>


Dear Beloved,

I am Barrister James Okoro. You have been identified as next of kin to the late Mr. Henry, whose inheritance
fund of USD 4,500,000 is waiting. Kindly reply to my private email claims.desk@barrister-office.example with
your full name, phone number and bank details so the processing fee can be arranged. This is urgent.

Regards,
Barrister James Okoro
"""


def make_app(tmp):
    cfg = Config(db_path=os.path.join(tmp, "u.db"), owner_emails=[OWNER], inbox=INBOX, mock=True,
                 public_url="https://uncle.example")
    return App(cfg)


class IntakeTests(unittest.TestCase):
    def test_blocked_attachment_falls_back_to_inline_forward(self):
        def blocked(_):
            raise RuntimeError("endpoint is not supported by the AgentMail connector")
        msg = {"text": GMAIL_FORWARD, "attachments": [{"attachment_id": "a1", "content_type": "message/rfc822"}]}
        p = intake.extract_scam(msg, blocked, {OWNER, INBOX})
        self.assertEqual(p["source"], "inline")
        self.assertEqual(p["from_addr"], "james.okoro@outlook-mail.example")

    def test_address_typed_above_the_forward_wins(self):
        text = GMAIL_FORWARD.replace("Uncle, this one's for you.", "Reply-to is real.agent@mailbox.example")
        p = intake.parse_forward(text)
        p["candidates"] = intake.candidates(p, {OWNER, INBOX})
        self.assertEqual(p["candidates"][0], "real.agent@mailbox.example")
        eng = make_app(tempfile.mkdtemp()).engine
        self.assertEqual(eng._pick_address(p), "real.agent@mailbox.example")

    def test_gmail_inline_forward(self):
        p = intake.parse_forward(GMAIL_FORWARD)
        self.assertEqual(p["from_addr"], "james.okoro@outlook-mail.example")
        self.assertIn("Inheritance", p["subject"])
        self.assertTrue(p["body"].startswith("Dear Beloved"))
        self.assertEqual(p["note"], "Uncle, this one's for you.")
        c = intake.candidates(p, {OWNER, INBOX})
        self.assertEqual(c[0], "claims.desk@barrister-office.example")
        self.assertIn("james.okoro@outlook-mail.example", c)
        self.assertNotIn(OWNER, c)

    def test_apple_forward_with_reply_to(self):
        text = ("Begin forwarded message:\n\nFrom: Prize Office <noreply@prize.example>\nSubject: You won\n"
                "Date: 26 November 2026\nTo: me@gmail.com\nReply-To: agent.claims@prize-agent.example\n\n"
                "Congratulations winner! Send the release fee.")
        p = intake.parse_forward(text)
        self.assertEqual(p["reply_to"], "agent.claims@prize-agent.example")
        self.assertEqual(intake.candidates(p, set())[0], "agent.claims@prize-agent.example")

    def test_eml_attachment(self):
        eml = (b"From: Lottery Board <board@lotto.example>\r\nReply-To: claims@lotto-agent.example\r\n"
               b"Subject: Winner notification\r\nContent-Type: text/plain\r\n\r\nYou won 1,000,000 USD.\r\n")
        p = intake.parse_eml(eml)
        self.assertEqual(p["reply_to"], "claims@lotto-agent.example")
        self.assertIn("You won", p["body"])

    def test_no_forward(self):
        self.assertIsNone(intake.parse_forward("hey uncle how are you"))


class PersonaTests(unittest.TestCase):
    def test_check_blocks_leaks(self):
        ok = "Well hello. " * 30
        self.assertEqual(persona.check_letter(ok), [])
        self.assertIn("contains a web address", persona.check_letter(ok + " visit www.bank.example now"))
        self.assertIn("contains an email address", persona.check_letter(ok + " write to a@b.com"))
        self.assertIn("contains a long number", persona.check_letter(ok + " my card is 4111 1111 1111 1111"))
        self.assertIn("claims to have sent money", persona.check_letter(ok + " I have sent the money."))
        self.assertIn("breaks character or mentions police", persona.check_letter(ok + " As an AI I cannot."))
        self.assertEqual(persona.check_letter(ok + " back in 1987 the Buick ran fine"), [])

    def test_fallback_passes_own_check(self):
        self.assertEqual(persona.check_letter(persona.FALLBACK), [])

    def test_tidy(self):
        t = persona.tidy("Subject: Re: hello\n\n**Dear** friend,\n\nHi\n\n---\nnotes from the model")
        self.assertNotIn("Subject", t)
        self.assertNotIn("**", t)
        self.assertNotIn("notes from the model", t)

    def test_write_letter_rewrites_bad_draft(self):
        class Bad:
            def __init__(self):
                self.n = 0

            def chat(self, messages, **kw):
                self.n += 1
                good = "Hello friend. " * 25 + "\n\nVern"
                return "Call me at 555 123 4567 " + good if self.n == 1 else good
        llm = Bad()
        text, problems = persona.write_letter(llm, persona.opening_messages("s", "b"))
        self.assertEqual(llm.n, 2)
        self.assertIn("contains a long number", problems)
        self.assertNotIn("555", text)


class RedactTests(unittest.TestCase):
    def test_redacts(self):
        t = redact.redact("I am Barrister James Okoro. Call +234 803 555 0199 or mail x@y.com, see www.fund.example. "
                          "Account 0123456789.\n\nRegards,\nJames Okoro", names=["James Okoro"])
        for leak in ("803", "x@y.com", "fund.example", "0123456789", "Okoro", "James"):
            self.assertNotIn(leak, t)
        self.assertIn("Barrister", t)


    def test_owner_words_hidden_everywhere(self):
        os.environ["REDACT_WORDS"] = "Priya Rao, Example Institute"
        try:
            self.assertNotIn("Example Institute", redact.subject("NOTICE 1 - Example Institute | Training program"))
            self.assertNotIn("Priya Rao", redact.redact("Dear Priya Rao, send the fee."))
            self.assertNotIn("priya rao", redact.private("my niece priya rao says hi"))
            self.assertIn("Training program", redact.subject("NOTICE 1 - Example Institute | Training program"))
        finally:
            del os.environ["REDACT_WORDS"]


class AgentMailConnectorTests(unittest.TestCase):
    def test_message_read_falls_back_to_its_thread(self):
        calls = []

        def fake_request(method, url, body=None, headers=None, timeout=30):
            calls.append(url)
            if "/messages/%3Cm2%40x%3E" in url:
                raise clients.net.HttpError(403, '{"error":"endpoint is not supported"}', url)
            if "/messages?limit=" in url:
                return {"messages": [{"message_id": "<m1@x>", "thread_id": "t9"},
                                     {"message_id": "<m2@x>", "thread_id": "t7"}]}
            if url.endswith("/threads/t7"):
                return {"messages": [{"message_id": "<m0@x>", "text": "old"},
                                     {"message_id": "<m2@x>", "text": "Fwd: the scam"}]}
            raise AssertionError(url)

        real = clients.net.request
        clients.net.request = fake_request
        try:
            am = clients.AgentMail(endpoint=gateway.Endpoint("https://gw.example/agentmail/c1", {}))
            self.assertEqual(am.get_message("u@agentmail.to", "<m2@x>")["text"], "Fwd: the scam")
            self.assertTrue(calls[-1].endswith("/threads/t7"))
        finally:
            clients.net.request = real


class PageMathTests(unittest.TestCase):
    def test_time_wasted_counts_reading_and_writing(self):
        from uncle import web
        self.assertEqual(web.wasted_seconds({"uncle_words_read": 400, "scammer_words": 50}), 240)
        self.assertEqual(web.wasted_seconds({}), 0)

    def test_wake_strip_marks_only_the_last_day(self):
        from uncle import web
        now = 1_800_000_000
        svg = web.wake_strip([{"started_at": now - 3600, "last_seen": now - 3000},
                              {"started_at": now - 90000, "last_seen": now - 89000}], now)
        self.assertEqual(svg.count("<rect"), 1)
        self.assertIn("over 1 wake-up;", svg)
        self.assertIn("Awake 10 m", svg)


class GatewayTests(unittest.TestCase):
    def test_parse_list(self):
        doc = {"connections": [
            {"provider": "agentmail", "gateway_base_url": "https://api.sprites.dev/v1/gateway/agentmail/conn_a"},
            {"provider": "typesafeai", "gateway_base_url": "https://api.sprites.dev/v1/gateway/typesafeai/conn_b"},
            {"provider": "ollama-cloud", "gateway_base_url": "https://api.sprites.dev/v1/gateway/ollama/conn_c"},
        ]}
        self.assertTrue(gateway.parse_gateway_list(doc, ["typesafe"]).endswith("conn_b"))
        self.assertTrue(gateway.parse_gateway_list(doc, ["ollama"]).endswith("conn_c"))
        self.assertIsNone(gateway.parse_gateway_list(doc, ["pinecone"]))


class ProviderTests(unittest.TestCase):
    """No TypeSafe credits: Clef on the Ollama key decides, and letters fall back across models."""

    def setUp(self):
        self._request = clients.net.request

    def tearDown(self):
        clients.net.request = self._request

    def test_ollama_falls_back_to_a_model_the_plan_allows(self):
        tried = []

        def fake(method, url, body=None, headers=None, timeout=60, retries=2):
            tried.append(body["model"])
            if body["model"] == "gpt-oss:120b":
                raise clients.net.HttpError(403, "this model requires a subscription", url)
            return {"message": {"content": "Well hello there!"}}

        clients.net.request = fake
        llm = clients.Ollama(endpoint=gateway.Endpoint("https://ollama.test"), model="gpt-oss:120b, gemma4")
        self.assertEqual(llm.chat([{"role": "user", "content": "hi"}]), "Well hello there!")
        self.assertEqual(llm.model, "gemma4")
        llm.chat([{"role": "user", "content": "again"}])
        self.assertEqual(tried, ["gpt-oss:120b", "gemma4", "gemma4"])  # remembers the one that worked

    def test_last_model_error_is_raised(self):
        def fake(method, url, body=None, headers=None, timeout=60, retries=2):
            raise clients.net.HttpError(402, "out of credit", url)

        clients.net.request = fake
        llm = clients.Ollama(endpoint=gateway.Endpoint("https://ollama.test"), model="a,b")
        with self.assertRaises(clients.net.HttpError):
            llm.chat([{"role": "user", "content": "hi"}])

    def test_clef_uses_the_ollama_service_and_same_questions(self):
        seen = {}

        def fake(method, url, body=None, headers=None, timeout=60, retries=2):
            seen.update(url=url, body=body)
            return {"answers": {"is_scam": {"type": "noul", "noul": 0.97}}}

        clients.net.request = fake
        d = clients.Jev(endpoint=gateway.Endpoint("https://ollama.test"), provider="ollama")
        self.assertEqual((d.service, d.model, d.name), ("ollama", "clef", "Clef"))
        a = d.ask("Send the fee", {"is_scam": clients.noul("Is this a scam?")})
        self.assertEqual(clients.p_yes(a, "is_scam"), 0.97)
        self.assertTrue(seen["url"].endswith("/v1/systemone"))
        self.assertEqual(seen["body"]["model"], "clef")

    def test_page_names_clef_when_ollama_decides(self):
        from uncle import server, web
        old = dict(web.DECIDER)
        try:
            self.assertEqual(server.pick_decider("ollama"), "ollama")
            with tempfile.TemporaryDirectory() as tmp:
                app = make_app(tmp)  # mock mode names Jev; the real App names whichever decider it picked
                web.DECIDER.update(name="Clef", maker="Ollama", about="Ollama's decision model")
                html = app.home_html()
            self.assertIn("Clef (Ollama's decision model)", html)
            self.assertIn("Ollama Cloud (Clef for every decision, and his voice)", html)
            self.assertNotIn("TypeSafe", html)
        finally:
            web.DECIDER.clear()
            web.DECIDER.update(old)


class _Block:
    def __init__(self, text):
        self.type, self.text = "text", text


class _Resp:
    def __init__(self, text, stop_reason="end_turn"):
        self.content, self.stop_reason, self.stop_details = [_Block(text)], stop_reason, None


class FakeAnthropic:
    """Stands in for anthropic.Anthropic(): answers decisions as JSON, letters as text."""

    def __init__(self, refuse=False):
        self.calls, self.refuse = [], refuse
        self.beta = self
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        if self.refuse:
            return _Resp("", "refusal")
        fmt = kw["output_config"].get("format")
        if not fmt:
            return _Resp(clients.MOCK_LETTERS[0])
        out = {}
        for key, spec in fmt["schema"]["properties"].items():
            fields = spec["properties"]
            if "p_yes" in fields:
                out[key] = {"p_yes": 0.05 if "stop" in key else 0.96}
            elif "choice" in fields:
                out[key] = {"choice": fields["choice"]["enum"][0], "confidence": 0.9}
            else:
                out[key] = {"level": 9, "confidence": 0.6}  # out of range on purpose
        return _Resp(json.dumps(out))


class ClaudeTests(unittest.TestCase):
    def test_decisions_come_back_in_jevs_shape(self):
        from uncle import claude
        fake = FakeAnthropic()
        c = claude.Claude(client=fake)
        a = c.ask({"their_reply": "Send the fee now!"}, {
            "is_scam": clients.noul("Is this a scam?"),
            "wants_stop": clients.noul("Do they want to stop?"),
            "kind": clients.choice("What kind?", {"advance_fee": "inheritance", "other": "other"}),
            "mood": clients.score("How cross?", ["calm", "pushy", "cross"]),
        })
        self.assertEqual(clients.p_yes(a, "is_scam"), 0.96)
        self.assertEqual(clients.p_yes(a, "wants_stop"), 0.05)
        self.assertEqual(clients.picked(a, "kind"), ("advance_fee", 0.9))
        self.assertEqual(clients.scored(a, "mood"), 2.0)  # clamped to the top level
        kw = fake.calls[0]
        self.assertEqual(kw["model"], "claude-opus-5-5")
        self.assertEqual(kw["fallbacks"], "default")
        self.assertIn("server-side-fallback-2026-07-01", kw["betas"])
        self.assertEqual(kw["output_config"]["effort"], "low")
        self.assertFalse(kw["output_config"]["format"]["schema"]["additionalProperties"])
        self.assertNotIn("temperature", kw)

    def test_letters_move_system_out_and_start_with_the_user(self):
        from uncle import claude
        fake = FakeAnthropic()
        msgs = persona.reply_messages([("uncle", "Hello friend."), ("scammer", "Send the fee.")], "fee", 2)
        text = claude.Claude(client=fake).chat(msgs)
        self.assertTrue(text.startswith("Well hello"))
        kw = fake.calls[0]
        self.assertIn("Vern", kw["system"])
        self.assertEqual(kw["messages"][0]["role"], "user")
        self.assertTrue(all(m["role"] != "system" for m in kw["messages"]))

    def test_refusal_raises(self):
        from uncle import claude
        with self.assertRaises(claude.Refused):
            claude.Claude(client=FakeAnthropic(refuse=True)).chat([{"role": "user", "content": "hi"}])

    def test_try_box_runs_on_claude_alone(self):
        from uncle import claude, web
        old_d, old_v = dict(web.DECIDER), dict(web.VOICE)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                cfg = Config(db_path=os.path.join(tmp, "u.db"), owner_emails=[OWNER], inbox=INBOX, mock=True)
                c = claude.Claude(client=FakeAnthropic())
                app = App(cfg, jev=c, llm=c)
                out = app.engine.try_uncle(GMAIL_FORWARD, "1.2.3.4")
                self.assertEqual(out["decider"], "Claude")
                self.assertTrue(out["letter"])
                self.assertIn("Anthropic (Claude for every decision and his voice)", app.home_html())
        finally:
            web.DECIDER.clear(); web.DECIDER.update(old_d)
            web.VOICE.clear(); web.VOICE.update(old_v)


class MeterTests(unittest.TestCase):
    def test_summary(self):
        rows = [{"started_at": 0, "last_seen": 3600, "cpu_start": 0, "cpu_last": 360, "mem_sum": 2.0,
                 "mem_samples": 4, "disk_gb": 1.0}]
        s = meter.summarize(rows)
        self.assertEqual(s["awake_s"], 3600)
        # 0.1 CPU-hour, 0.5 GB for an hour, 1 GB disk for an hour
        expect = 0.1 * meter.CPU_HOUR + 0.5 * meter.GB_HOUR + 1.0 * meter.HOT_STORAGE_GB_HOUR
        self.assertAlmostEqual(s["cost_usd"], expect, places=9)

    def test_gap_starts_new_wake(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(tmp)
            m = app.meter
            m._new_wake(1000.0)
            first = m.boot_id
            m.beat(now=1004.0)
            m.beat(now=1600.0)  # ten minutes of silence: he was asleep
            self.assertNotEqual(first, m.boot_id)
            s = meter.summarize(app.store.q("SELECT * FROM boots"))
            self.assertAlmostEqual(s["awake_s"], 4.0)


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = make_app(self.tmp.name)
        self.mail = self.app.mail
        self.eng = self.app.engine

    def tearDown(self):
        self.tmp.cleanup()

    def forward_and_approve(self):
        mid, owner_tid = self.mail.deliver(OWNER, "Fwd: URGENT inheritance", GMAIL_FORWARD)
        self.assertEqual(self.eng.handle(mid), "intake")
        approval = self.mail.outbox[-1]
        self.assertEqual(approval["kind"], "reply")
        self.assertIn("claims.desk@barrister-office.example", approval["text"])
        self.assertIn("Reply \"yes\"", approval["text"])
        t = self.app.store.q("SELECT * FROM threads")[0]
        self.assertEqual(t["status"], "pending_approval")
        mid2, _ = self.mail.deliver(OWNER, "Re: Fwd", "yes go get him", thread_id=owner_tid)
        self.assertEqual(self.eng.handle(mid2), "owner_command")
        sent = [o for o in self.mail.outbox if o["kind"] == "send"]
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["to"], "claims.desk@barrister-office.example")
        return self.app.store.thread(t["id"]), sent[0]

    def test_blocked_reply_falls_back_to_fresh_email_and_yes_still_works(self):
        def blocked(*_):
            raise clients.net.HttpError(403, '{"error":"endpoint is not supported"}', "reply")
        self.mail.reply = blocked
        mid, owner_tid = self.mail.deliver(OWNER, "Fwd: URGENT inheritance", GMAIL_FORWARD)
        self.assertEqual(self.eng.handle(mid), "intake")
        ask = self.mail.outbox[-1]
        self.assertEqual((ask["kind"], ask["to"]), ("send", OWNER))
        self.assertTrue(ask["subject"].startswith("Re: "))
        self.assertIn("Reply \"yes\"", ask["text"])
        # The boss answers in the new thread, and Uncle writes to the scammer.
        mid2, _ = self.mail.deliver(OWNER, "Re: Fwd", "yes", thread_id=ask["thread_id"])
        self.assertEqual(self.eng.handle(mid2), "owner_command")
        sent = [o for o in self.mail.outbox if o["kind"] == "send" and o["to"] != OWNER]
        self.assertEqual(sent[0]["to"], "claims.desk@barrister-office.example")
        # The scammer writes back; Uncle can't reply in-thread either, so he sends a fresh "Re:".
        scammer = "claims.desk@barrister-office.example"
        mid3, _ = self.mail.deliver(scammer, "Re: URGENT", "Dear Vern, kindly send the processing fee today.",
                                    thread_id=sent[0]["thread_id"])
        self.assertEqual(self.eng.handle(mid3), "scammer")
        letter = self.mail.outbox[-2] if self.mail.outbox[-1]["to"] == OWNER else self.mail.outbox[-1]
        self.assertEqual((letter["kind"], letter["to"]), ("send", scammer))
        self.assertTrue(letter["subject"].startswith("Re: "))
        # Their next letter lands in that new mail thread, or another, and still reaches the right pen pal.
        mid4, _ = self.mail.deliver(scammer, "Re: Re: URGENT", "Vern, the fee. Western Union. Today.",
                                    thread_id="some-other-thread")
        self.assertEqual(self.eng.handle(mid4), "scammer")

    def test_spam_only_counts_from_the_boss_or_a_pen_pal(self):
        mid, _ = self.mail.deliver("random@spammer.example", "Cheap pills", "Buy now, kindly reply.")
        self.mail.messages[mid]["labels"].append("spam")
        self.assertEqual(self.eng.handle(mid), "spam")
        self.assertEqual(self.mail.outbox, [])
        fwd, _ = self.mail.deliver(OWNER, "Fwd: URGENT inheritance", GMAIL_FORWARD)
        self.mail.messages[fwd]["labels"].append("spam")
        self.assertEqual(self.eng.handle(fwd), "intake")

    def test_bounce_closes_the_thread_and_tells_the_boss(self):
        t, sent = self.forward_and_approve()
        mid, _ = self.mail.deliver("MAILER-DAEMON@amazonses.example", "Delivery Status Notification (Failure)",
                                   "An error occurred while trying to deliver the mail to the following "
                                   "recipients:\nclaims.desk@barrister-office.example")
        self.assertEqual(self.eng.handle(mid), "bounce")
        t = self.app.store.thread(t["id"])
        self.assertEqual((t["status"], t["close_reason"]), ("closed", "their address bounced"))
        self.assertIn("bounced", self.mail.outbox[-1]["text"])

    def test_awake_hold_is_harmless_off_a_sprite(self):
        from uncle import awake
        with awake.held():
            pass

    def test_uncle_gossips_about_other_pen_pals_without_their_details(self):
        self.forward_and_approve()
        mid, _ = self.mail.deliver(OWNER, "Fwd: URGENT inheritance", GMAIL_FORWARD)
        self.eng.handle(mid)
        system = self.app.llm.calls[-1][0]["content"]
        self.assertIn("Your other pen pals", system)
        self.assertIn("millions waiting for me", system)
        self.assertIn("Dale", system)
        for secret in ("claims.desk@barrister-office.example", "Okoro", "4.5"):
            self.assertNotIn(secret, system.split("Your other pen pals")[1])

    def test_resend_approval(self):
        mid, _ = self.mail.deliver(OWNER, "Fwd: URGENT inheritance", GMAIL_FORWARD)
        self.eng.handle(mid)
        tid = self.app.store.q("SELECT id FROM threads")[0]["id"]
        before = len(self.mail.outbox)
        self.assertTrue(self.eng.resend_approval(tid).startswith("sent"))
        self.assertEqual(len(self.mail.outbox), before + 1)

    def test_full_loop(self):
        t, sent = self.forward_and_approve()
        self.assertEqual(t["status"], "active")
        # The scammer writes back in the same thread.
        mid, _ = self.mail.deliver("claims.desk@barrister-office.example", "Re: URGENT",
                                   "Dear Vern, kindly send the processing fee by Western Union today. Urgent!",
                                   thread_id=sent["thread_id"])
        self.assertEqual(self.eng.handle(mid), "scammer")
        replies = [o for o in self.mail.outbox if o["kind"] == "reply" and o["in_reply_to"] == mid]
        self.assertEqual(len(replies), 1)
        self.assertEqual(persona.check_letter(replies[0]["text"]), [])
        # Owner is told about the first bite.
        self.assertTrue(any("They bit" in o["text"] for o in self.mail.outbox))
        tot = self.app.store.totals()
        self.assertEqual(tot["bit"], 1)
        self.assertEqual(tot["scammer_letters"], 1)
        # Same webhook twice does nothing.
        self.assertEqual(self.eng.handle(mid), "duplicate")
        # Page renders and the thread page shows a redacted letter.
        html = self.app.home_html()
        self.assertIn("Uncle Vern", html)
        self.assertIn("URGENT", html)
        th = self.app.thread_html(t["id"])
        self.assertIn("Western Union", th)

    def test_share_cards_and_link_previews(self):
        from uncle import card
        t, sent = self.forward_and_approve()
        mid, _ = self.mail.deliver("claims.desk@barrister-office.example", "Re: URGENT",
                                   "Dear Vern, kindly send the processing fee by Western Union today.",
                                   thread_id=sent["thread_id"])
        self.eng.handle(mid)
        spec = web.thread_share(self.app.cfg, self.app.store.thread(t["id"]), self.app.store.letters(t["id"]))
        self.assertEqual(spec["url"], f"uncle.example/t/{t['id']}")
        self.assertIn("2 letters from Uncle, 1 back", spec["facts"])
        self.assertTrue(any("of their time wasted" in f for f in spec["facts"]))
        if not card.available():
            self.assertIsNone(self.app.card_png(t["id"]))
            self.skipTest("Pillow is not installed")
        png = self.app.card_png(t["id"])
        self.assertTrue(png.startswith(b"\x89PNG"))
        self.assertIs(self.app.card_png(t["id"]), png)  # cached until the next letter
        self.assertTrue(self.app.card_png("home").startswith(b"\x89PNG"))
        th = self.app.thread_html(t["id"])
        self.assertIn(f'og:image" content="https://uncle.example/card/{t["id"]}.png?v=', th)
        self.assertIn("summary_large_image", th)
        self.assertIn("x.com/intent/tweet", th)
        self.assertIn("https://uncle.example/card/home.png?v=", self.app.home_html())
        # A hidden conversation has no card.
        self.app.store.update_thread(t["id"], hidden=1)
        self.assertIsNone(self.app.card_png(t["id"]))

    def test_scammer_names_are_blacked_out_of_uncles_letters_too(self):
        t, sent = self.forward_and_approve()
        lid = self.app.store.q("SELECT id FROM letters WHERE direction='uncle'")[0]["id"]
        self.app.store.run("UPDATE letters SET public_body=? WHERE id=?",
                           ("Dear Barrister Okoro,\n\nJames, my nephew Dale says hi. Doug too.\n\nVern", lid))
        page = self.app.thread_html(t["id"])
        for name in ("Okoro", "James"):
            self.assertNotIn(name, page)
        for kept in ("Dale", "Doug", "Vern"):
            self.assertIn(kept, page)
        self.assertEqual(redact.names_in("Kindly reply.\n\nBest regards,\nPeter Obi"), ["Peter Obi"])
        self.assertEqual(redact.names_in("Thanks,\nsend the fee today and God bless you"), [])

    def test_a_visitor_forward_gets_a_practice_letter_and_the_scammer_gets_nothing(self):
        judge = "judge@fly.example"
        mid, _ = self.mail.deliver(judge, "Fwd: URGENT inheritance", GMAIL_FORWARD)
        self.mail.messages[mid]["labels"].append("spam")  # forwarded scams usually arrive marked spam
        self.assertEqual(self.eng.handle(mid), "visitor")
        self.assertEqual(len(self.mail.outbox), 1)
        out = self.mail.outbox[0]
        self.assertEqual(out["kind"], "reply")
        self.assertIn("Here's what I'd write back", out["text"])
        self.assertIn("nothing went to the scammer", out["text"])
        self.assertEqual(self.app.store.q("SELECT * FROM threads"), [])  # no pen pal, no approval asked
        self.assertIn("practice letter", self.app.store.diary(1)[0]["text"])
        self.assertNotIn(judge, self.app.home_html())
        self.assertIn(f"mailto:{INBOX}", self.app.home_html())

    def test_visitor_limits_and_non_scams(self):
        judge = "judge@fly.example"
        mid, _ = self.mail.deliver(judge, "Fwd: lunch", "---------- Forwarded message ---------\nFrom: Sam "
                                   "<sam@friend.example>\nSubject: lunch\n\nLunch on Thursday at noon?")
        self.eng.handle(mid)
        self.assertEqual(len(self.mail.outbox), 1)
        self.assertIn("sit this one out", self.mail.outbox[0]["text"])
        self.app.cfg.visitor_per_day = 1
        mid2, _ = self.mail.deliver(judge, "Fwd: URGENT inheritance", GMAIL_FORWARD)
        self.assertEqual(self.eng.handle(mid2), "visitor")
        self.assertEqual(len(self.mail.outbox), 1)  # over the limit: no more mail
        # A scammer "forwarding" their own pitch is not a visitor: no practice letter goes back to them.
        fake, _ = self.mail.deliver("james.okoro@outlook-mail.example", "Fwd: URGENT inheritance", GMAIL_FORWARD)
        self.mail.messages[fake]["labels"].append("spam")
        self.eng.handle(fake)
        self.assertEqual(len(self.mail.outbox), 1)
        forged, _ = self.mail.deliver("other@fly.example", "Fwd: URGENT inheritance", GMAIL_FORWARD)
        self.mail.messages[forged]["labels"].append("unauthenticated")
        self.eng.handle(forged)
        self.assertEqual(len(self.mail.outbox), 1)

    def test_stop_request_closes(self):
        t, sent = self.forward_and_approve()
        n_before = len(self.mail.outbox)
        mid, _ = self.mail.deliver("claims.desk@barrister-office.example", "Re:", "Please stop emailing me, wrong person.",
                                   thread_id=sent["thread_id"])
        self.eng.handle(mid)
        self.assertEqual(self.app.store.thread(t["id"])["status"], "closed")
        self.assertFalse(any(o.get("in_reply_to") == mid for o in self.mail.outbox[n_before:]))

    def test_decline(self):
        mid, owner_tid = self.mail.deliver(OWNER, "Fwd: URGENT", GMAIL_FORWARD)
        self.eng.handle(mid)
        mid2, _ = self.mail.deliver(OWNER, "Re", "no don't", thread_id=owner_tid)
        self.eng.handle(mid2)
        self.assertEqual(self.app.store.q("SELECT status FROM threads")[0]["status"], "declined")
        self.assertFalse(any(o["kind"] == "send" for o in self.mail.outbox))

    def test_not_a_scam_is_left_alone(self):
        text = "Hey, forwarding the bake sale schedule.\n\n---------- Forwarded message ---------\n" \
               "From: Church Office <office@church.example>\nSubject: Bake sale\n\nSee you Saturday at ten."
        mid, _ = self.mail.deliver(OWNER, "Fwd: Bake sale", text)
        self.eng.handle(mid)
        self.assertEqual(self.app.store.q("SELECT status FROM threads")[0]["status"], "rejected")
        self.assertFalse(any(o["kind"] == "send" for o in self.mail.outbox))

    def test_stranger_not_scam_ignored(self):
        mid, _ = self.mail.deliver("friend@example.com", "Hi", "Hi Vern, are you coming to bingo on Thursday?")
        self.assertEqual(self.eng.handle(mid), "stranger")
        self.assertEqual(self.mail.outbox, [])

    def test_stranger_scam_asks_owner_then_replies_in_thread(self):
        scam = ("Dear friend, you are the beneficiary of an inheritance fund of USD 2 million. Kindly send the "
                "processing fee by Western Union and your bank details. Urgent claim, reply now.")
        mid, scam_tid = self.mail.deliver("agent@scam.example", "Inheritance claim", scam)
        self.eng.handle(mid)
        ask = self.mail.outbox[-1]
        self.assertEqual(ask["kind"], "send")
        self.assertEqual(ask["to"], OWNER)
        mid2, _ = self.mail.deliver(OWNER, "Re", "yes", thread_id=ask["thread_id"])
        self.eng.handle(mid2)
        last = self.mail.outbox[-2]  # the reply to the scammer, then the note to the owner
        self.assertEqual(last["kind"], "reply")
        self.assertEqual(last["in_reply_to"], mid)
        t = self.app.store.q("SELECT * FROM threads")[0]
        self.assertEqual(t["am_thread_id"], scam_tid)

    def test_try_box_rate_limit(self):
        scam = "Congratulations winner! Your lottery prize of USD 1 million is ready. Pay the release fee by gift card."
        for _ in range(self.app.cfg.try_per_ip_hour):
            r = self.eng.try_uncle(scam, "1.2.3.4")
            self.assertIn("letter", r)
        self.assertIn("error", self.eng.try_uncle(scam, "1.2.3.4"))
        self.assertIn("letter", self.eng.try_uncle(scam, "5.6.7.8"))

    def test_catch_up_processes_missed_mail(self):
        mid, _ = self.mail.deliver(OWNER, "Fwd: URGENT", GMAIL_FORWARD)
        n = self.eng.catch_up()
        self.assertEqual(n, 1)
        self.assertEqual(self.app.store.known_message(mid)["status"], "done")


if __name__ == "__main__":
    unittest.main()
