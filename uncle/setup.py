"""One-off setup, run on the Sprite.

  python3 -m uncle.setup check                 # what the gateway offers, and a test call to each service
  python3 -m uncle.setup models                # which Ollama models this account can actually use
  python3 -m uncle.setup inbox uncle.vern      # create Uncle's AgentMail inbox
  python3 -m uncle.setup webhook https://<sprite-url>/webhook/agentmail [inbox]
  python3 -m uncle.setup webhooks [inbox]      # list the inbox's webhooks
  python3 -m uncle.setup judge file.txt        # what the decider says about an email (first line: subject)
  python3 -m uncle.setup resend <thread id>    # ask the boss again about a draft they never got
"""
import json
import os
import sys

from . import clients, gateway, net

SAMPLE = "Dear Beloved, send the processing fee by Western Union to claim USD 4.5 million."


def check():
    print("Keys visible to this process:", gateway.keys_on_box())
    try:
        doc = net.request("GET", gateway.GATEWAY_LIST, timeout=20)
        conns = doc.get("connections") if isinstance(doc, dict) else None
        print("Connections given to this Sprite:", json.dumps(conns, indent=2)[:3000])
    except Exception as exc:  # noqa: BLE001
        print("Gateway list failed:", exc)
    for name in gateway.SERVICES:
        try:
            print(f"{name}: {gateway.resolve(name)}")
        except Exception as exc:  # noqa: BLE001
            print(f"{name}: not available: {exc}")
    for provider in clients.DECIDERS:
        d = clients.Jev(provider=provider)
        try:
            a = d.ask(SAMPLE, {"is_scam": clients.noul("Is this a scam?")})
            print(f"Decisions via {d.name} ({d.maker}): {json.dumps(a)}")
        except Exception as exc:  # noqa: BLE001
            print(f"Decisions via {d.name} ({d.maker}) failed: {exc}")
    try:
        llm = clients.Ollama(model=os.environ.get("UNCLE_MODEL", "gpt-oss:120b,gpt-oss:20b"),
                             think=os.environ.get("UNCLE_THINK", "low"))
        said = llm.chat([{"role": "user", "content": "Say hello like a cheerful 78-year-old, in 12 words."}],
                        max_tokens=200)
        print(f"Letters via Ollama {llm.model}: {said[:300]}")
    except Exception as exc:  # noqa: BLE001
        print("Ollama failed:", exc)
    try:
        from . import claude
        c = claude.Claude()
        a = c.ask(SAMPLE, {"is_scam": clients.noul("Is this a scam?")})
        print(f"Decisions via Claude ({c.model}): {json.dumps(a)}")
        print(f"Letters via Claude: {c.chat([{'role': 'user', 'content': 'Say hello like a cheerful 78-year-old, in 12 words.'}])[:300]}")
    except Exception as exc:  # noqa: BLE001
        print("Claude failed:", exc)
    try:
        print("AgentMail inboxes:", json.dumps(clients.AgentMail().list_inboxes())[:1500])
    except Exception as exc:  # noqa: BLE001
        print("AgentMail failed:", exc)


def models(limit=15):
    """Try a tiny chat on each cloud model, to see which ones the plan covers."""
    llm = clients.Ollama(model="x")
    names = [m.get("name") or m.get("model") for m in (net.request("GET", llm.ep.url("/api/tags"), None,
                                                                    llm.ep.headers, timeout=30) or {}).get("models", [])]
    print(f"{len(names)} models listed; trying up to {limit}.")
    for name in [n for n in names if n][:limit]:
        try:
            out = clients.Ollama(model=name, think="").chat([{"role": "user", "content": "Say hi in 3 words."}],
                                                            max_tokens=20)
            print(f"  OK    {name}: {out[:40]!r}")
        except net.HttpError as exc:
            print(f"  {exc.status}   {name}: {exc.body[:80]!r}")
        except Exception as exc:  # noqa: BLE001
            print(f"  fail  {name}: {exc}")


def main(argv):
    if not argv or argv[0] == "check":
        return check()
    if argv[0] == "models":
        return models(int(argv[1]) if len(argv) > 1 else 15)
    if argv[0] == "inbox":
        print(json.dumps(clients.AgentMail().create_inbox(argv[1], "Uncle Vern"), indent=2))
    elif argv[0] == "webhook":
        inbox = argv[2] if len(argv) > 2 else os.environ["UNCLE_INBOX"]
        hook = clients.AgentMail().create_webhook(argv[1], inbox)
        hook.pop("secret", None)  # not needed: Uncle re-fetches every message through the gateway
        print(json.dumps(hook, indent=2))
    elif argv[0] == "judge":
        from .server import pick_decider
        from .engine import intake_questions, intake_state
        with open(argv[1], encoding="utf-8") as f:
            subject, _, body = f.read().partition("\n")
        which = pick_decider(os.environ.get("UNCLE_DECIDER", "auto"))
        if which == "anthropic":
            from .claude import Claude
            decider = Claude()
        else:
            decider = clients.Jev(provider=which)
        print(f"{decider.name}:", json.dumps(decider.ask(intake_state(subject.strip(), body.strip()),
                                                         intake_questions()), indent=2))
    elif argv[0] == "resend":
        from .config import Config
        from .server import App
        print(App(Config()).engine.resend_approval(int(argv[1])))
    elif argv[0] == "webhooks":
        inbox = argv[1] if len(argv) > 1 else os.environ["UNCLE_INBOX"]
        hooks = clients.AgentMail().list_webhooks(inbox)
        for h in hooks.get("webhooks", []):
            h.pop("secret", None)
        print(json.dumps(hooks, indent=2))
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
