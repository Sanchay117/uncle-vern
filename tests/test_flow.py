import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uncle import clients, gateway, intake, memory, meter, persona, redact, voice, web, websearch  # noqa: E402
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

    def test_outlook_forwards(self):
        body = "I hope you don't mind me reaching out this way! I came across your profile."
        web_text = ("andrea.w@gmail.com\n\n________________________________\nFrom: Andrea <andreawendy@proton.me>\n"
                    "Sent: Monday, November 2, 2026 3:26 AM\nTo: Student <student@uni.example>\n"
                    f"Subject: Thought I'd reach out.\n\n{body}")
        web_html = ('<div>andrea.w@gmail.com</div><hr style="display:inline-block;width:98%" tabindex="-1">'
                    '<div id="divRplyFwdMsg" dir="ltr"><font face="Calibri" style="font-size:11pt"><b>From:</b> '
                    'Andrea &lt;andreawendy@proton.me&gt;<br><b>Sent:</b> Monday, November 2, 2026 3:26 AM<br>'
                    '<b>To:</b> Student &lt;student@uni.example&gt;<br><b>Subject:</b> Thought I\'d reach out.'
                    f'</font><div>&nbsp;</div></div><div>{body}</div>')
        desktop = ("andrea.w@gmail.com\n\n-----Original Message-----\nFrom: Andrea <andreawendy@proton.me>\n"
                   "Sent: Monday, November 2, 2026 3:26 AM\nTo: student@uni.example\n"
                   f"Subject: Thought I'd reach out.\n\n{body}")
        for msg in ({"text": web_text}, {"html": web_html}, {"text": desktop}):
            p = intake.extract_scam(msg, lambda _: None, {"student@uni.example", INBOX})
            self.assertIsNotNone(p, msg)
            self.assertEqual(p["from_addr"], "andreawendy@proton.me")
            self.assertEqual(p["subject"], "Thought I'd reach out.")
            self.assertTrue(p["body"].startswith("I hope you don't mind"), p["body"])
            self.assertEqual(p["candidates"][0], "andrea.w@gmail.com")  # the typed reply-to wins
            self.assertNotIn("student@uni.example", p["candidates"])
        self.assertTrue(intake.looks_forwarded({"subject": "FW: Thought I'd reach out.", "text": web_text}))

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
        # One nephew, always Dale: the judge caught a Kyle and a Randy in older letters.
        self.assertEqual(persona.check_letter(ok + " My nephew Dale set this up."), [])
        self.assertTrue(persona.check_letter(ok + " My nephew Kyle set this up."))
        self.assertTrue(persona.check_letter(ok + " My niece Randi says hello."))

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

    def test_the_name_a_scam_was_addressed_to_is_hidden(self):
        t = redact.redact("Dear Priya Rao,\n\nYou have won.\nHello Sam! Pay the fee.")
        self.assertNotIn("Priya", t)
        self.assertNotIn("Sam", t)
        self.assertIn("You have won", t)
        for generic in ("Dear Friend,", "Dear Sir/Madam,", "Dear Beneficiary,", "Hello there,", "Dear Valued Customer,",
                        "Dear Vern,", "Hello Uncle Vern,", "Dear Mr. Pickett,"):
            self.assertIn(generic, redact.redact(generic + "\n\nPay the fee."))


    def test_uncle_never_names_who_the_scam_was_sent_to(self):
        ok = "Dear friend, " + "I am so happy to hear from you about this. " * 8 + "\n\nVern"
        os.environ["REDACT_WORDS"] = "Priya, Example Institute"
        try:
            self.assertIn("names the person the email was really sent to",
                          persona.check_letter("He said it was meant for some young fella named Priya. " + ok))
            self.assertIn("names the person the email was really sent to",
                          persona.check_letter("Something from example institute. " + ok))
            self.assertEqual(persona.check_letter(ok), [])
        finally:
            del os.environ["REDACT_WORDS"]

    def test_webmail_or_an_organisations_own_domain(self):
        for a in ("mail2offline@gmail.com", "ggmailbox@tutamail.com", "x@yahoo.co.uk", "y@outlook.com",
                  "z@proton.me", "w@hotmail.fr"):
            self.assertTrue(intake.webmail(a), a)
        for a in ("sumaish@corizo.in", "info@bda.com.sa", "alphaport625@c4c.ecoknights.org.my",
                  "x@mail.example-corp.com"):
            self.assertFalse(intake.webmail(a), a)

    def test_owner_words_hidden_everywhere(self):
        os.environ["REDACT_WORDS"] = "Priya Rao, Example Institute"
        try:
            self.assertNotIn("Example Institute", redact.subject("NOTICE 1 - Example Institute | Training program"))
            self.assertNotIn("Priya Rao", redact.redact("Dear Priya Rao, send the fee."))
            self.assertNotIn("priya rao", redact.private("my niece priya rao says hi"))
            self.assertIn("Training program", redact.subject("NOTICE 1 - Example Institute | Training program"))
        finally:
            del os.environ["REDACT_WORDS"]


class MemoryTests(unittest.TestCase):
    def test_families_group_threads_either_way_round(self):
        rows = [{"id": 1, "kin": None}, {"id": 2, "kin": "[[1, 0.9]]"}, {"id": 3, "kin": "[[2, 0.8]]"},
                {"id": 4, "kin": "[]"}, {"id": 5, "kin": "not json"}]
        self.assertEqual(memory.families(rows), [[1, 2, 3]])

    def test_pinecone_embed_request(self):
        seen = {}

        def fake(method, url, body=None, headers=None, timeout=60, retries=2):
            seen.update(method=method, url=url, body=body, headers=headers)
            return {"data": [{"values": [3.0, 4.0]}, {"values": [0.0, 2.0]}], "usage": {"total_tokens": 9}}
        old, os.environ["PINECONE_API_KEY"] = clients.net.request, "pc-test"
        clients.net.request = fake
        try:
            e = memory.PineconeEmbedder()
            self.assertTrue(e.available())
            self.assertEqual(e.embed(["Dear friend", "Greetings"]), [[0.6, 0.8], [0.0, 1.0]])  # unit length
        finally:
            clients.net.request = old
            del os.environ["PINECONE_API_KEY"]
        self.assertEqual((seen["method"], seen["url"]), ("POST", "https://api.pinecone.io/embed"))
        self.assertEqual(seen["headers"]["Api-Key"], "pc-test")
        self.assertIn("X-Pinecone-API-Version", seen["headers"])
        self.assertEqual(seen["body"]["model"], "llama-text-embed-v2")
        self.assertEqual(seen["body"]["inputs"][1], {"text": "Greetings"})
        self.assertEqual(seen["body"]["parameters"]["input_type"], "passage")

    def test_vectors_survive_the_disk(self):
        v = [0.25, -0.5, 0.75]
        self.assertEqual(memory.unpack(memory.pack(v)), v)
        self.assertIsNone(memory.unpack("not base64!"))

    def test_no_connector_means_no_memory_and_no_fuss(self):
        old = memory.gateway.resolve

        def missing(name):
            raise RuntimeError("No Sprites connector found for pinecone")
        memory.gateway.resolve = missing
        try:
            self.assertFalse(memory.PineconeEmbedder().available())
            with tempfile.TemporaryDirectory() as d:
                from uncle.store import Store
                s = Store(os.path.join(d, "m.db"))
                m = memory.Memory(s, memory.PineconeEmbedder())
                self.assertEqual(m.backfill(), 0)
        finally:
            memory.gateway.resolve = old

    def test_an_old_disk_gets_the_new_column(self):
        import sqlite3
        from uncle.store import SCHEMA, Store
        self.assertNotRegex(SCHEMA, r"\bkin\b")  # the live disk was made before memory, without the column
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "old.db")
            db = sqlite3.connect(path)
            db.executescript(SCHEMA)
            db.execute("INSERT INTO threads(scam_text) VALUES('old one')")
            db.commit()
            db.close()
            s = Store(path)
            self.assertTrue({"kin", "vec"} <= {r["name"] for r in s.q("PRAGMA table_info(threads)")})
            self.assertEqual(s.q("SELECT scam_text, kin FROM threads"), [{"scam_text": "old one", "kin": None}])
            # A disk with reranker kin but no vectors yet gets its kin redone with embeddings.
            s.update_thread(1, kin="[]")
            s.db.execute("ALTER TABLE threads DROP COLUMN vec")
            s = Store(path)
            self.assertEqual(s.q("SELECT kin FROM threads"), [{"kin": None}])


class WebSearchTests(unittest.TestCase):
    SCAM = ("Dear Priya, I am Barrister James Okoro. Your late relative left an unclaimed fund that only you can "
            "receive through our chambers this month. Call +234 801 234 5678 or write to claims@law.example today.")

    def test_copies_need_six_words_in_a_row_one_page_per_site(self):
        phrase = "left an unclaimed fund that only you can receive through our chambers"
        results = [
            {"url": "https://www.scamwarners.example/t/1", "title": "Inheritance scam",
             "description": "Your late relative left an unclaimed fund that only you can receive..."},
            {"url": "https://scamwarners.example/t/2", "title": "Same again", "description": phrase},
            {"url": "https://blog.example/a", "title": "Funds", "description": "unclaimed fund that only you"},
            # Whole words only: "yleft" isn't "left".
            {"url": "https://other.example/b", "title": "x", "description": "yleft an unclaimed fund that only"},
        ]
        found = websearch.copies(phrase, results)
        self.assertEqual([f["site"] for f in found], ["scamwarners.example"])
        self.assertEqual(websearch.copies(phrase, []), [])

    def test_only_a_clean_sentence_goes_to_the_web(self):
        good = "Your late relative left an unclaimed fund that only you can receive"
        self.assertEqual(websearch.good_quote(good, self.SCAM), good)
        # Not in the email, too short, or carrying a name, address or number: fall back to a clean sentence.
        for bad in ("A sentence that is not in this email at all, sadly", "Your late relative",
                    "I am Barrister James Okoro.", "Dear Priya, I am Barrister James Okoro."):
            q = websearch.good_quote(bad, self.SCAM)
            self.assertTrue(q.startswith("Your late relative left"), q)
        self.assertIsNone(websearch.good_quote("", "Call +234 801 234 5678 or write to claims@law.example now."))
        old = os.environ.get("REDACT_WORDS")
        os.environ["REDACT_WORDS"] = "chambers"
        try:
            self.assertFalse(websearch.safe("receive through our chambers this month"))
        finally:
            os.environ.pop("REDACT_WORDS")
            if old is not None:
                os.environ["REDACT_WORDS"] = old

    def test_web_check_remembers_and_keeps_to_its_daily_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            from uncle.store import Store
            s = websearch.MockSearch()
            w = websearch.WebCheck(Store(os.path.join(tmp, "s.db")), s, per_day=1)
            r = w.check("one sentence from a scam letter going round", wait=1)
            self.assertEqual([f["site"] for f in r["found"]], ["scam-warnings.example"])
            self.assertEqual(w.check("one sentence from a scam letter going round")["at"], r["at"])
            self.assertIsNone(w.check("a different sentence entirely, over the cap"))
            self.assertIsNone(w.check(""))
            self.assertEqual(len(s.queries), 1)
        self.assertIn("no copies yet", websearch.web_line({"phrase": "x", "found": [], "at": 1}))
        self.assertEqual(websearch.web_line({"phrase": "x"}), "")  # not back yet: say nothing
        self.assertEqual(websearch.web_line(None), "")

    def test_apify_run_poll_and_read(self):
        seen = []

        def fake(method, url, body=None, headers=None, timeout=60, retries=2):
            seen.append((method, url, body, headers))
            if url.endswith("/runs"):
                return {"data": {"id": "r1", "status": "RUNNING"}}
            if "/actor-runs/" in url:
                return {"data": {"id": "r1", "status": "SUCCEEDED", "defaultDatasetId": "d1"}}
            return [{"organicResults": [{"url": "https://a.example", "title": "t", "description": "d"}]}]
        old, os.environ["APIFY_TOKEN"] = websearch.net.request, "ap-test"
        old_sleep, websearch.time.sleep = websearch.time.sleep, lambda s: None
        websearch.net.request = fake
        try:
            a = websearch.ApifySearch()
            self.assertTrue(a.available())
            self.assertEqual(a.search("left an unclaimed fund")[0]["url"], "https://a.example")
        finally:
            websearch.net.request, websearch.time.sleep = old, old_sleep
            del os.environ["APIFY_TOKEN"]
        self.assertEqual(seen[0][1], "https://api.apify.com/v2/actors/apify~google-search-scraper/runs")
        self.assertEqual(seen[0][2]["queries"], '"left an unclaimed fund"')
        self.assertEqual(seen[0][3]["Authorization"], "Bearer ap-test")
        self.assertEqual(seen[1][1], "https://api.apify.com/v2/actor-runs/r1")
        self.assertEqual(seen[2][1], "https://api.apify.com/v2/datasets/d1/items?clean=true")


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


class VoiceTests(unittest.TestCase):
    def test_deepgram_speak_request(self):
        seen = {}

        def fake(method, url, body=None, headers=None, timeout=60, retries=2):
            seen.update(method=method, url=url, body=body, headers=headers)
            return b"ID3" + b"\0" * 2000
        old, os.environ["DEEPGRAM_API_KEY"] = voice.net.request, "dg-test"
        voice.net.request = fake
        try:
            audio = voice.Deepgram().synth("Well hello.")
        finally:
            voice.net.request = old
            del os.environ["DEEPGRAM_API_KEY"]
        self.assertTrue(audio.startswith(b"ID3"))
        self.assertEqual(seen["url"], "https://api.deepgram.com/v1/speak?model=aura-2-pluto-en&encoding=mp3")
        self.assertEqual(seen["headers"]["Authorization"], "Token dg-test")
        self.assertEqual(seen["body"], {"text": "Well hello."})

    def test_what_gets_read_out(self):
        self.assertEqual(voice.speakable("Dear ███ ███,\n\n\n\nWell   hello."), "Dear ,\n\nWell hello.")
        long = "Doug took my glasses. " * 200
        out = voice.speakable(long)
        self.assertLessEqual(len(out), voice.MAX_CHARS)
        self.assertTrue(out.endswith("glasses."))

    def test_each_letter_is_recorded_once_and_there_is_a_daily_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            speaker = voice.MockSpeaker()
            v = voice.Voice(tmp, speaker, per_day=1)
            first = v.audio("Well hello there, friend.")
            self.assertEqual(v.audio("Well hello there, friend."), first)
            self.assertEqual(speaker.calls, 1)
            self.assertIsNone(v.audio("A different letter altogether."))  # over today's limit
            self.assertEqual(speaker.calls, 1)

    def test_no_connector_means_the_browser_reads_it(self):
        old = voice.gateway.resolve

        def missing(name):
            raise RuntimeError("No Sprites connector found for deepgram")
        voice.gateway.resolve = missing
        try:
            self.assertFalse(voice.Deepgram().available())
        finally:
            voice.gateway.resolve = old


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

    def test_claude_answers_list_questions(self):
        from uncle import claude
        qs = {"red_flags": clients.listing("Red flags?", 2)}
        schema = claude._schema(qs)
        self.assertEqual(schema["properties"]["red_flags"]["properties"]["items"]["type"], "array")
        self.assertIn("a list, at most 2 items", claude._question_text(qs))
        a = claude.to_jev(qs, {"red_flags": {"items": ["asks for a fee ", "", "x" * 300, "third"]}})
        self.assertEqual(clients.listed(a, "red_flags"), ["asks for a fee", "x" * 200])
        self.assertEqual(clients.listed({}, "red_flags"), [])
        self.assertTrue(claude.Claude.lists)

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
        self.assertIn("Careful: barrister-office.example isn't a free email service", approval["text"])
        self.assertIn("Reply \"yes\"", approval["text"])
        t = self.app.store.q("SELECT * FROM threads")[0]
        self.assertEqual(t["status"], "pending_approval")
        mid2, _ = self.mail.deliver(OWNER, "Re: Fwd", "yes go get him", thread_id=owner_tid)
        self.assertEqual(self.eng.handle(mid2), "owner_command")
        sent = [o for o in self.mail.outbox if o["kind"] == "send"]
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["to"], "claims.desk@barrister-office.example")
        return self.app.store.thread(t["id"]), sent[0]

    def test_uncle_reads_only_his_own_letters_aloud(self):
        # Before the boss says yes, the letter isn't on the page, so there's nothing to hear.
        mid, _ = self.mail.deliver(OWNER, "Fwd: URGENT inheritance", GMAIL_FORWARD)
        self.eng.handle(mid)
        pending = self.app.store.q("SELECT id FROM letters")
        self.assertTrue(all(self.app.letter_audio(l["id"]) is None for l in pending))
        self.tmp.cleanup()
        self.tmp = tempfile.TemporaryDirectory()
        self.app = make_app(self.tmp.name)
        self.mail, self.eng = self.app.mail, self.app.engine
        t, _ = self.forward_and_approve()
        mine = self.app.store.q("SELECT id FROM letters WHERE direction='uncle'")[0]["id"]
        self.assertIn(f'data-voice="/voice/letter/{mine}.mp3"', self.app.thread_html(t["id"]))
        self.assertTrue(self.app.letter_audio(mine).startswith(b"ID3"))
        self.assertIsNone(self.app.letter_audio(mine + 999))
        # The try box: a link for the letter Uncle just wrote, and nothing for text he didn't.
        j = self.app.with_voice(self.eng.try_uncle(GMAIL_FORWARD, "1.2.3.4"))
        key = j["voice"].split("/")[-1][:-4]
        self.assertEqual(self.app.voice.try_text(key), j["letter"])
        self.assertIsNone(self.app.voice.try_text("0" * 32))

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
        other = GMAIL_FORWARD.replace("claims.desk@barrister-office.example", "second.desk@gmail.com")
        mid, _ = self.mail.deliver(OWNER, "Fwd: URGENT inheritance", other)
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
        self.assertIn("Nothing has gone to the scammer", out["text"])
        # A company's own domain is too often a real business or a hacked box: no pen pal, no approval asked.
        self.assertEqual(self.app.store.q("SELECT * FROM threads"), [])
        self.assertIn("practice letter", self.app.store.diary(1)[0]["text"])
        self.assertNotIn(judge, self.app.home_html())
        self.assertIn(f"mailto:{INBOX}", self.app.home_html())

    def test_a_visitor_gets_the_verdict_and_can_play_the_scammer(self):
        judge = "judge@fly.example"
        mid, _ = self.mail.deliver(judge, "Fwd: URGENT inheritance", GMAIL_FORWARD)
        self.assertEqual(self.eng.handle(mid), "visitor")
        first = self.mail.outbox[0]["text"]
        self.assertIn("Yes, it's a scam", first)
        self.assertIn("The red flags:\n- asks for a fee before you get paid", first)
        self.assertIn("Apify found the same words on 1 other page", first)
        self.assertIn("scam-warnings.example", first)
        self.assertNotIn("support.mail.example", first)  # a help page isn't a copy
        self.assertIn("Reply to this email as the scammer", first)
        searched = self.app.web.searcher.queries
        self.assertEqual(len(searched), 1)
        for secret in ("claims.desk", "Okoro", "4,500,000", "me@gmail.com"):
            self.assertNotIn(secret, searched[0])
        # They reply in the same mail thread, as the scammer.
        tid = self.mail.outbox[0]["thread_id"]
        r1, _ = self.mail.deliver(judge, "Re: Fwd: URGENT inheritance",
                                  "Why you not send the fee? Send it now, this is urgent!", thread_id=tid)
        self.assertEqual(self.eng.handle(r1), "practice")
        a1 = self.mail.outbox[-1]
        self.assertEqual(a1["kind"], "reply")
        self.assertIn("Practice, round 1 of 5", a1["text"])
        self.assertIn("Nothing goes to any real scammer", a1["text"])
        self.assertIn("still hooked", a1["text"])
        self.assertEqual(persona.check_letter(a1["text"].split("\n------------------------------")[0]), [])
        # The connector sometimes can't reply in a thread, so Uncle starts a new one: still the same game.
        self.app.cfg.practice_rounds = 3
        r2, _ = self.mail.deliver(judge, "Re: Fwd: URGENT inheritance", "Old man, the fee. Today.")
        self.assertEqual(self.eng.handle(r2), "practice")
        self.assertIn("round 2 of 3", self.mail.outbox[-1]["text"])
        r3, _ = self.mail.deliver(judge, "Re: Fwd: URGENT inheritance", "Last chance, send the fee", thread_id=tid)
        self.eng.handle(r3)
        self.assertIn("That was the last round", self.mail.outbox[-1]["text"])
        n = len(self.mail.outbox)
        r4, _ = self.mail.deliver(judge, "Re: Fwd: URGENT inheritance", "Hello??", thread_id=tid)
        self.eng.handle(r4)
        self.assertEqual(len(self.mail.outbox), n)  # the game is over
        # Nothing ever went to the scammer, and the game stays off the page.
        self.assertFalse([o for o in self.mail.outbox if o.get("to") == "claims.desk@barrister-office.example"])
        self.assertEqual(self.app.store.q("SELECT * FROM letters"), [])
        home = self.app.home_html()
        self.assertNotIn(judge, home)
        self.assertNotIn("Old man", home)
        self.assertIn("reply to him as the scammer", home)
        # A new forward from the same person is a new scam, not a move in the old game.
        f2, _ = self.mail.deliver(judge, "Fwd: another one", GMAIL_FORWARD)
        self.assertEqual(self.eng.handle(f2), "visitor")

    def test_playing_the_scammer_stops_when_they_ask(self):
        judge = "judge2@fly.example"
        mid, _ = self.mail.deliver(judge, "Fwd: URGENT inheritance", GMAIL_FORWARD)
        self.eng.handle(mid)
        tid = self.mail.outbox[0]["thread_id"]
        r1, _ = self.mail.deliver(judge, "Re: Fwd", "Please stop writing to me, wrong person.", thread_id=tid)
        self.assertEqual(self.eng.handle(r1), "practice")
        self.assertIn("I'd stop writing here, because you asked me to stop", self.mail.outbox[-1]["text"])
        n = len(self.mail.outbox)
        r2, _ = self.mail.deliver(judge, "Re: Fwd", "Wait, send the fee", thread_id=tid)
        self.eng.handle(r2)
        self.assertEqual(len(self.mail.outbox), n)
        # Practice replies have their own daily count: playing doesn't use up anybody's forwards.
        self.app.cfg.visitor_per_day = 1
        other = "judge3@fly.example"
        m3, _ = self.mail.deliver(other, "Fwd: URGENT inheritance", GMAIL_FORWARD)
        self.eng.handle(m3)
        t3 = self.mail.outbox[-1]["thread_id"]
        for i in range(2):
            ri, _ = self.mail.deliver(other, "Re: Fwd", f"Send the fee now {i}", thread_id=t3)
            self.eng.handle(ri)
        self.assertIn("round 2 of 5", self.mail.outbox[-1]["text"])
        forged, _ = self.mail.deliver(other, "Re: Fwd", "Send the fee", thread_id=t3)
        self.mail.messages[forged]["labels"].append("unauthenticated")
        n = len(self.mail.outbox)
        self.eng.handle(forged)
        self.assertEqual(len(self.mail.outbox), n)

    def test_the_verdict_reaches_the_boss_and_the_page(self):
        t, _ = self.forward_and_approve()
        approval = [o for o in self.mail.outbox if o["kind"] == "reply"][0]["text"]
        self.assertTrue(approval.startswith("Jev puts it at"))
        self.assertIn("The red flags:", approval)
        self.assertIn("Apify found the same words", approval)
        page = self.app.thread_html(t["id"])
        self.assertIn('class="verdict"', page)
        self.assertIn("asks for a fee before you get paid", page)
        self.assertIn('href="https://scam-warnings.example/2026/11/a"', page)
        self.assertIn("rel=\"noopener nofollow\"", page)
        for secret in ("claims.desk@barrister-office.example", "Okoro"):
            self.assertNotIn(secret, page)
        self.assertIn("Apify (looks for copies of each scam on the web)", self.app.home_html())

    def test_rounds_fill_in_verdicts_for_older_conversations(self):
        t, _ = self.forward_and_approve()
        self.app.store.update_thread(t["id"], flags=None, web=None)
        self.assertNotIn('class="verdict"', self.app.thread_html(t["id"]))
        self.assertEqual(self.eng.rounds()["verdicts"], 2)  # red flags, then the web search
        t = self.app.store.thread(t["id"])
        self.assertIn("asks for a fee", t["flags"])
        self.assertIn('"at"', t["web"])
        self.assertIn('class="verdict"', self.app.thread_html(t["id"]))
        self.assertEqual(self.eng.fill_in(), 0)  # nothing left to do
        # A search that didn't come back in time is finished on a later round, from the cache when it can.
        self.app.store.update_thread(t["id"], web=json.dumps({"phrase": json.loads(t["web"])["phrase"]}))
        before = len(self.app.web.searcher.queries)
        self.assertEqual(self.eng.fill_in(), 1)
        self.assertEqual(len(self.app.web.searcher.queries), before)
        # A broken search is noted and tried again later; it never stops the rounds.
        self.app.store.update_thread(t["id"], web=json.dumps({"phrase": "a sentence nobody searched for before"}))

        def broken(query, wait=90):
            raise RuntimeError("Apify run FAILED")
        self.app.web.searcher.search = broken
        self.assertEqual(self.eng.rounds()["verdicts"], 0)
        self.assertNotIn('"at"', self.app.store.thread(t["id"])["web"])

    def test_try_box_shows_the_red_flags(self):
        j = self.eng.try_uncle(GMAIL_FORWARD, "1.2.3.4")
        self.assertIn("asks for a fee before you get paid", j["flags"])
        self.assertIn("j.flags", self.app.home_html())

    def test_one_follow_up_after_a_day_of_silence(self):
        t, first = self.forward_and_approve()
        later = time.time() + 25 * 3600
        self.assertEqual(self.eng.nudge_due(time.time() + 3600), 0)  # too soon
        self.assertEqual(self.eng.nudge_due(later), 1)
        nudge = self.mail.outbox[-1]
        self.assertEqual((nudge["kind"], nudge["to"]), ("send", "claims.desk@barrister-office.example"))
        self.assertTrue(nudge["subject"].startswith("Re: "))
        self.assertEqual(persona.check_letter(nudge["text"]), [])
        self.assertEqual(len([l for l in self.app.store.letters(t["id"]) if l["direction"] == "uncle"]), 2)
        self.assertIn("make sure my letter got there", self.app.store.diary(1)[0]["text"])
        self.assertEqual(self.eng.nudge_due(later + 48 * 3600), 0)  # only ever once
        # Rounds also pick up anything the webhook missed.
        r = self.eng.rounds()
        self.assertEqual((r["caught_up"], r["nudged"]), (0, 0))
        prompt = self.app.llm.calls[-1][-1]["content"]
        self.assertIn("heard nothing back", prompt)
        # A visit or the hourly ping asks for rounds, at most once in a while.
        self.assertTrue(self.app.queue_rounds())
        self.assertFalse(self.app.queue_rounds())

    def test_no_follow_up_once_they_write(self):
        t, sent = self.forward_and_approve()
        mid, _ = self.mail.deliver("claims.desk@barrister-office.example", "Re: URGENT",
                                   "Dear Vern, kindly send the processing fee.", thread_id=sent["thread_id"])
        self.eng.handle(mid)
        self.assertEqual(self.eng.nudge_due(time.time() + 25 * 3600), 0)

    def test_first_letters_are_short_and_keen(self):
        msgs = persona.opening_messages("URGENT", "Kindly send your details.")
        self.assertIn("70 to 130 words", msgs[-1]["content"])
        self.assertIn("never a dollar amount", msgs[-1]["content"])

    def test_uncle_remembers_a_script_from_a_new_address(self):
        first, _ = self.forward_and_approve()
        again = GMAIL_FORWARD.replace("claims.desk@barrister-office.example", "new.desk77@gmail.com")
        mid, owner_tid = self.mail.deliver(OWNER, "Fwd: URGENT inheritance", again)
        self.eng.handle(mid)
        ask = self.mail.outbox[-1]
        self.assertRegex(ask["text"], rf"remembers this script: it's \d+% like #{first['id']} ")
        self.assertIn("which I'm writing to at claims.desk@barrister-office.example", ask["text"])
        second = self.app.store.q("SELECT * FROM threads ORDER BY id DESC")[0]
        (kin_id, kin_score), = memory.kin_of(second)
        self.assertEqual(kin_id, first["id"])
        self.assertGreaterEqual(kin_score, self.app.cfg.memory_same)
        self.assertIn("I've had this letter before", self.app.store.diary(5, second["id"])[0]["text"])
        # Only conversations on the page are linked; until then it's a count. Once both are, each links the other.
        page = self.app.thread_html(first["id"])
        self.assertIn("Uncle has had this same letter 1 more time, from another address.", page)
        self.assertNotIn(f'href="/t/{second["id"]}"', page)
        yes, _ = self.mail.deliver(OWNER, "Re: Fwd", "yes", thread_id=owner_tid)
        self.eng.handle(yes)
        self.assertIn(f'href="/t/{second["id"]}"', self.app.thread_html(first["id"]))
        self.assertIn("Seen this script before", self.app.thread_html(second["id"]))
        home = self.app.home_html()
        self.assertIn("Same script, new address", home)
        self.assertIn("one script, 2 letters, from 2 addresses", home)

    def test_rounds_fill_in_memory_for_older_threads(self):
        first, _ = self.forward_and_approve()
        self.app.store.update_thread(first["id"], kin=None)
        self.assertEqual(self.eng.rounds()["remembered"], 1)
        self.assertEqual(self.app.store.thread(first["id"])["kin"], "[]")

    def test_the_same_scammer_twice_gets_one_letter(self):
        t, _ = self.forward_and_approve()
        n = len(self.mail.outbox)
        mid, _ = self.mail.deliver(OWNER, "Fwd: URGENT inheritance", GMAIL_FORWARD)
        self.eng.handle(mid)
        self.assertIn("I'm already writing to claims.desk@barrister-office.example", self.mail.outbox[-1]["text"])
        self.assertEqual(len(self.mail.outbox), n + 1)
        self.assertEqual(len(self.app.store.q("SELECT * FROM threads")), 1)
        self.app.store.update_thread(t["id"], status="closed", close_reason="their address bounced")
        mid2, _ = self.mail.deliver(OWNER, "Fwd: URGENT inheritance", GMAIL_FORWARD)
        self.eng.handle(mid2)
        self.assertIn("I already tried claims.desk@barrister-office.example, and their address bounced",
                      self.mail.outbox[-1]["text"])
        self.assertEqual(len(self.app.store.q("SELECT * FROM threads")), 1)

    def test_the_boss_can_paste_a_scam_instead_of_forwarding(self):
        body = ("barrister.okoro77@gmail.com\n\nDear Friend, I am Barrister James Okoro. My late client left "
                "US$10.5 million with no next of kin. Kindly reply with your full name and phone number so we can "
                "process the transfer to you. Reply urgently to this email for the details.")
        mid, _ = self.mail.deliver(OWNER, "inheritance scam from WhatsApp", body)
        self.assertEqual(self.eng.handle(mid), "intake")
        t = self.app.store.q("SELECT * FROM threads")[0]
        self.assertEqual((t["status"], t["scammer_addr"]), ("pending_approval", "barrister.okoro77@gmail.com"))
        self.assertNotIn("barrister.okoro77", t["scam_text"])
        # A note with no scam in it still gets the how-to, which now mentions pasting.
        mid2, _ = self.mail.deliver(OWNER, "hi", "hey uncle, how are you doing today?")
        self.eng.handle(mid2)
        self.assertIn("paste it into a new email", self.mail.outbox[-1]["text"])

    def test_a_friends_forward_becomes_a_real_pen_pal_on_the_bosss_yes(self):
        friend = "friend@college.example"
        fwd = GMAIL_FORWARD.replace("claims.desk@barrister-office.example", "barrister.okoro77@gmail.com")
        mid, _ = self.mail.deliver(friend, "Fwd: URGENT inheritance", "Dear Priya,\n\n" + fwd)
        self.assertEqual(self.eng.handle(mid), "visitor")
        ask = next(o for o in self.mail.outbox if o.get("to") == OWNER)
        practice = next(o for o in self.mail.outbox if o["kind"] == "reply")
        self.assertIn("asked my boss", practice["text"])
        self.assertEqual((ask["kind"], ask["to"]), ("send", OWNER))
        self.assertIn("I'd like to write to: barrister.okoro77@gmail.com", ask["text"])
        self.assertIn(friend, ask["text"])  # the boss sees who sent it; the page never does
        self.assertIn("Only say yes if you know who sent it", ask["text"])
        t = self.app.store.q("SELECT * FROM threads")[0]
        self.assertEqual(t["status"], "pending_approval")
        self.assertNotIn(friend, self.app.home_html())
        # Nothing reaches the scammer until the boss says yes in that thread.
        self.assertFalse([o for o in self.mail.outbox if o.get("to") == "barrister.okoro77@gmail.com"])
        yes, _ = self.mail.deliver(OWNER, "Re: A friend sent me a scam", "yes", thread_id=ask["thread_id"])
        self.assertEqual(self.eng.handle(yes), "owner_command")
        sent = [o for o in self.mail.outbox if o.get("to") == "barrister.okoro77@gmail.com"]
        self.assertEqual(len(sent), 1)
        self.assertEqual(self.app.store.thread(t["id"])["status"], "active")
        # The same scammer forwarded again by someone else isn't asked about twice.
        again, _ = self.mail.deliver("other@college.example", "Fwd: URGENT inheritance", fwd)
        self.eng.handle(again)
        self.assertEqual(len(self.app.store.q("SELECT * FROM threads")), 1)

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

    def test_judge_test_fixes_on_the_pages(self):
        home = self.app.home_html()
        self.assertIn("0 scammers have his letter", home)
        self.assertIn('id="sample"', home)
        self.assertLess(home.index('id="try"'), home.index('id="mailbag"'))
        t, sent = self.forward_and_approve()
        home = self.app.home_html()
        self.assertIn("1 scammer has his letter", home)
        self.assertIn("A real scam he", home)  # the real scam on his desk, not an empty in-tray
        # Until someone writes back, the scoreboard shows no columns that are zero by definition.
        self.assertIn('class="ledger three"', home)
        self.assertNotIn("Words scammers typed", home)
        self.assertIn("Addresses already shut down", home)
        self.assertNotIn("claims.desk@barrister-office.example", home)
        page = self.app.thread_html(t["id"])
        self.assertIn("The scam that started it", page)
        self.assertIn("next of kin", page)
        for secret in ("claims.desk@barrister-office.example", "Okoro"):
            self.assertNotIn(secret, page)
        self.assertIn("as the scammer wrote it", page)

    def test_play_the_scammer(self):
        first = self.eng.try_uncle(GMAIL_FORWARD, "1.2.3.4")
        self.assertTrue(first["letter"])
        turns = [{"who": "uncle", "text": first["letter"]}]
        r = self.eng.try_reply(GMAIL_FORWARD, turns, "Vern you must send the processing fee by Western Union "
                               "today, urgent!", "1.2.3.4")
        self.assertTrue(r["letter"])
        self.assertIn("still hooked", r["read"])
        self.assertIn("wants Uncle to", r["read"])
        stop = self.eng.try_reply(GMAIL_FORWARD, turns, "Please stop emailing me, wrong person.", "1.2.3.4")
        self.assertIsNone(stop["letter"])
        self.assertIn("stops writing", stop["note"])
        self.assertIn("error", self.eng.try_reply(GMAIL_FORWARD, [], "hello there", "1.2.3.4"))
        self.assertEqual(self.mail.outbox, [])  # practice never sends mail
        self.app.cfg.try_per_ip_hour = 3
        self.assertIn("nap", self.eng.try_reply(GMAIL_FORWARD, turns, "Send it now!", "1.2.3.4")["error"])

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
