"""LOCAL UI CHECK ONLY. Fills a throwaway mock database so the page can be looked at
before any real scammer writes back. Never deployed, never shown as results.

  UNCLE_DB=data/demo.db UNCLE_MOCK=1 python3 -m uncle.demo_seed
"""
import os

from .config import Config
from .server import App

FWD = """---------- Forwarded message ---------
From: Barrister Paul Ade <paul.ade@lawchambers.example>
Subject: Unclaimed Inheritance Fund of USD 4.5 Million
To: <me@gmail.com>

Dear Beloved, you are next of kin to an unclaimed inheritance fund. Kindly reply to
claims.office@lawchambers.example with your bank details so the processing fee can be arranged. Urgent."""


def main():
    owner = "owner@example.com"
    cfg = Config(owner_emails=[owner], inbox="uncle@agentmail.test", mock=True)
    app = App(cfg)
    app.meter.start()
    mail, eng = app.mail, app.engine
    mid, otid = mail.deliver(owner, "Fwd: inheritance", FWD)
    eng.handle(mid)
    mid, _ = mail.deliver(owner, "Re", "yes", thread_id=otid)
    eng.handle(mid)
    sent = [o for o in mail.outbox if o["kind"] == "send"][-1]
    for text in ["Dear Vern, thank you. Kindly go to Western Union today and send the processing fee. Urgent!",
                 "Vern why are you wasting time? Forget the ferret. Buy the gift card and send the code now to "
                 "my secretary Mrs. Grace Bello on WhatsApp +234 803 555 0192 or at www.lawchambers-claims.com "
                 "before 5pm.\n\nRegards,\nBarrister Paul Ade"]:
        mid, _ = mail.deliver("claims.office@lawchambers.example", "Re", text, thread_id=sent["thread_id"])
        eng.handle(mid)
    print("seeded", os.path.abspath(cfg.db_path))


if __name__ == "__main__":
    main()
