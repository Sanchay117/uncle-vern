# Uncle Vern

**Forward him a scam email. He writes back to the scammer, slowly, for as long as they'll keep answering.**

[Try him, no sign-up](https://uncle-vern-b6zgb.sprites.app) · Email him a scam: `uncle.vern@agentmail.to` · [Code](https://github.com/Sanchay117/uncle-vern)

Americans reported losing $12.5 billion to fraud in 2024, up 25% in a year, and older people lost the most per person ([FTC, March 2025](https://www.ftc.gov/news-events/news/press-releases/2025/03/new-ftc-data-show-big-jump-reported-losses-fraud-125-billion-2024)). Every scammer works through a list. Each hour one spends on a pen pal who will never pay is an hour they don't spend on someone's grandma.

So I built Uncle Vern. He's 78, retired from fixing school buses, and very keen to help the nice man with the inheritance. He's ready to go ahead, but Doug the ferret has hidden the checkbook, and could they spell that bank name one more time?

1. Forward a scam from your inbox to Uncle's.
2. Claude checks it's a scam and finds the address the scammer wants a reply at. Uncle emails you his first letter, and you reply "yes".
3. Uncle writes to the scammer, then sleeps. When they write back, he wakes and answers.

**Safety:** Uncle only writes to scams his owner forwards, and the owner says yes to the first letter. Every letter passes a checker that stops links, email addresses, numbers and real names going out. He never sends money, and he stops the minute anyone asks. On the public page, scammers' names, addresses and numbers are blacked out.

## For judges: try it in 60 seconds

1. Open https://uncle-vern-b6zgb.sprites.app on any device.
2. Under **Try him**, tap **Use a sample scam** (or paste one of your own), then **Ask Uncle to write back**. His letter appears in about 10 seconds. Nothing is sent to anyone.
3. Under his letter, **Now you be the scammer**: write back as them, push him to pay, tap **Send as the scammer**, and see how he wriggles out of it.
4. Scroll to **The mailbag** to read the real scammers he's writing to.

Or forward a real scam from your own inbox to `uncle.vern@agentmail.to`. He emails you the letter he'd send, usually within a minute.

## Why a Sprite

Scammers answer hours or days apart. Uncle has to be there when they do, and costs nothing while he waits.

- **Sleep and wake.** Uncle is a Sprite service. AgentMail's webhook wakes the Sprite when mail arrives. The Sprite then holds a task open through its local API while he writes, so it doesn't pause halfway through a letter.
- **Disk.** Every conversation lives in SQLite on the Sprite's own disk, so it survives every sleep.
- **Connector gateway.** No API key is stored on the box. AgentMail (his inbox) and Anthropic (Claude, which makes every decision and writes every letter) go through Fly's gateway. A scammer who talks Uncle into anything finds nothing to steal.
- **Pinecone, optional.** With a Pinecone connector, Pinecone's reranker gives Uncle a memory for scam scripts. When a new scam is the same letter as an old one from a different address, he says so. Without it, nothing else changes.

## Proof

As of Nov 27, 2026, all real and nothing planted:

- First letters went out to six live scammers. They came from the owner's own spam, sifted from about 1,100 emails: two Niger Delta "compensation" offers, a loan advisor, a lookalike steel company, a romance opener and an "is this the right email?" probe.
- Three more scam addresses had already been shut down when Uncle wrote, and their letters bounced.
- He declined one: a job offer from a real company's domain.
- No scammer has written back yet. When one does, the time-wasted counter on the home page starts.

## How it works

```
scam forwarded ──> AgentMail inbox ──webhook──> Sprite wakes
                                                   │
                      Claude: is it a scam? which address? (structured answer with a probability)
                                                   │
                    owner gets the draft by email ──"yes"──> letter goes to the scammer
                                                   │
           scammer replies ──webhook──> Claude reads it: still hooked? how cross? wants to stop?
                                                   │
                      Claude writes Uncle's reply ──> checker ──> sent ──> Sprite sleeps
```

- `uncle/engine.py`: the mail loop (intake, owner approval, replies, follow-ups, hourly rounds)
- `uncle/persona.py`: Uncle's voice and the letter checker
- `uncle/claude.py`: decisions and letters through the Anthropic connector
- `uncle/gateway.py`, `uncle/clients.py`: the Sprites connector gateway, AgentMail
- `uncle/memory.py`: script memory through Pinecone's reranker
- `uncle/redact.py`: what the public page blacks out
- `uncle/awake.py`, `uncle/meter.py`: holding the Sprite awake while working, and counting time awake
- `uncle/server.py`, `uncle/web.py`: the public page, try box and conversation pages
- `.github/workflows/rounds.yml`: an hourly ping that picks up any mail a webhook missed and sends one "did my letter reach you?" after a day of silence

Python 3 standard library only (plus the Anthropic SDK, and Pillow for share cards).

## Run it yourself

```bash
UNCLE_MOCK=1 python3 -m uncle.server
```

That runs the whole page locally with a fake model and fake mail, on http://localhost:8080. Tests: `python3 -m unittest discover -s tests`. To put him on your own Sprite, see [deploy/README.md](deploy/README.md).

Credit where it's due: Netsafe's Re:scam (New Zealand, 2017) and O2's Daisy (UK, 2024) wasted scammers' time for a whole country. Uncle Vern is one you run yourself.
