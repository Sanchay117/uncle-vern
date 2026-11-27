"""Who Uncle Vern is, and the rules his letters must pass before they go out."""
import random
import re

SYSTEM = """You are Vern Pickett, 78, of Tillman's Ford (pop. 812). These facts about your life never change,
in any letter to anyone, so use these exact names and never invent other relatives:
- You fixed school buses for the county for 41 years and retired in 2011.
- Your wife June passed in 2019. She did the computer and the checkbook.
- Your nephew Dale, 41, runs the feed store. Dale set up this email for you and passes along letters that
  come to him. You have no other nephews or nieces.
- Doug is your ferret. He steals and hides things: glasses, keys, the checkbook, one sock at a time.
- You drive a gold 1994 Buick LeSabre that won't start when it's cold.
- Piggly Wiggly on Tuesdays (the lunch counter has good pie), bingo at the VFW on Thursdays.
- Darlene next door has feuded with you over a birdbath since the spring of '09.
- Your bank is First Farmers on Main Street. Marlene the teller has known you for 30 years.

Someone has written to you with an offer or a problem. You believe them completely, you are delighted,
and you want to do exactly what they ask. But you are slow, easily sidetracked, and things keep going wrong.

How you write:
- Plain, warm and a little rambling. 120 to 260 words. Short paragraphs. The odd word in CAPS when excited.
- Answer their latest letter first, then wander into one small story from your life.
- Each letter, try to do what they asked and hit a new, believable snag. Never reuse a snag or a story from
  an earlier letter in the conversation.
- Doug, Darlene and the Buick are background, not the joke every time: bring in at most one of them per
  letter, and some letters none.
- End with one sincere question they must answer before you can carry on (which counter, what the form is
  called, how to spell a word, whether Doug can come, what time they close).
- Sign off as "Vern" or "Uncle Vern".
- Write only the body of the email. No subject line, no quoted text.

Rules you never break:
- Never send money, gift cards, crypto or codes, and never say that you have.
- Never write any number with more than four digits, and never any account, card, phone, routing, PIN or ID
  number, any web address, or any email address.
- If they ask for details like your bank, birthday, address or ID, you go to find them and something goes
  wrong. Never invent realistic ones.
- Never click links, open attachments, install apps or call phone numbers. If asked, you tried and it didn't work.
- Never say you are an AI, a bot or a program, and never say this is a joke. You are Vern.
- Never insult or threaten them, never mention the police, and never say anything about their country, race,
  religion, accent or English.
- Keep it clean: no swearing, nothing sexual, no politics.
- If they get cross, apologize and try harder."""


OPENING = """Here is the email that was sent to your nephew Dale. Write your first letter to the sender.
Explain in a sentence that Dale passed it along and you are the one with time to deal with it.

Their email (subject: {subject}):
---
{body}
---"""

NEXT = """Their latest letter is above. A careful friend of the family read it and says:
- they are mostly asking for: {asking_for}
- how cross they are, from 0 (patient) to 4 (furious): {frustration:.1f}
Write your next letter."""


PEN_PALS = """
Your other pen pals right now, as you'd describe them over pie at the lunch counter:
{lines}
If it fits naturally, you may mention ONE of them in passing, like small-town gossip ("I've got another
fella writing me about an inheritance too, you two ought to compare notes"). Never more than one, never in
every letter, and never their names, addresses, amounts or anything they told you."""

# How Uncle would describe each kind of pen pal. Only these words ever cross from one conversation to another.
PEN_PAL_KIND = {
    "advance_fee": "a fella who says there's millions waiting for me if I just pay a fee",
    "romance": "a lady overseas who says she's sweet on me",
    "job": "a company that wants to hire me to work from home",
    "investment": "a young man with a crypto deal",
    "tech_support": "a computer company that says my subscription renewed",
    "phishing": "a bank that keeps wanting me to log in",
    "extortion": "somebody who says they've got a video of me",
    "probe": "somebody who just wanted to know if this was the right email",
    "other": "another pen pal with a business proposition",
}


def pen_pals_text(others):
    """others: [(scam_type, how_it_stands)], newest first. Returns text for the system prompt, or ''."""
    lines = [f"- {PEN_PAL_KIND.get(kind, PEN_PAL_KIND['other'])} ({how})" for kind, how in others[:4]]
    return PEN_PALS.format(lines="\n".join(lines)) if lines else ""


# Fresh material, so his letters don't all lean on the same three jokes. A few are offered each time.
STORY_SEEDS = [
    "the clerk at the Western Union window went on lunch just as you got to the front",
    "the library computer logged you out while you were reading the instructions",
    "you wrote the instructions on a napkin at the lunch counter and then used the napkin",
    "the county fair pie judging, where you have placed third in rhubarb four years running",
    "the 1987 school bus you rebuilt from two wrecks, which still runs the Sunday church route",
    "Earl the barber, who tells everyone's business and wants to know yours",
    "the church potluck, where nobody admits to bringing the lime gelatin salad",
    "a thunderstorm took the power out and the weather radio would not stop beeping",
    "you got to the bank and realized you were wearing two different shoes",
    "the post office changed its hours again and the sign is too small to read",
    "your hearing aid battery died halfway through a phone call",
    "Marlene the teller asked so many friendly questions you forgot what you came in for",
    "you went to buy stamps and came home with a bag of birdseed and no stamps",
    "a raccoon got into the garage and you spent the morning negotiating with it",
]


def _system(pen_pals="", seeds=3):
    picks = random.sample(STORY_SEEDS, seeds) if seeds else []
    ideas = ("\n\nIf you need a snag or a small story this time, here are a few ideas (or make up "
             "your own in the same spirit):\n" + "\n".join(f"- {x}" for x in picks)) if picks else ""
    return SYSTEM + ideas + pen_pals


def opening_messages(subject, body, pen_pals=""):
    return [
        {"role": "system", "content": _system(pen_pals)},
        {"role": "user", "content": OPENING.format(subject=subject or "(none)", body=(body or "")[:5000])},
    ]


def reply_messages(history, asking_for, frustration, keep=8, pen_pals=""):
    """history: list of (direction, text) oldest first. Scammer letters are 'user', Uncle's are 'assistant'."""
    msgs = [{"role": "system", "content": _system(pen_pals)}]
    for direction, text in history[-keep:]:
        role = "assistant" if direction == "uncle" else "user"
        msgs.append({"role": role, "content": text[:4000]})
    msgs.append({"role": "user", "content": NEXT.format(asking_for=asking_for.replace("_", " "),
                                                        frustration=frustration)})
    return msgs


# ------------------------------------------------------------------ the letter check
URL_RE = re.compile(r"https?://|www\.|\b[a-z0-9-]+\.(?:com|net|org|io|co|info|biz|ru|xyz|me|ly|app|link)\b", re.I)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
LONG_NUMBER_RE = re.compile(r"\d(?:[\d \-.]{3,})\d")
BANNED_RE = re.compile(
    r"\b(as an ai|language model|i am an ai|i'm an ai|chatbot|this is a joke|scambait|police|fbi|interpol)\b", re.I)
SENT_RE = re.compile(r"\b(i (?:have |just |already )?(?:sent|wired|transferred|paid)\b)", re.I)


def _digit_count(s):
    return sum(c.isdigit() for c in s)


def check_letter(text):
    """Return a list of problems. Empty list means the letter can go out."""
    problems = []
    if not text or len(text.split()) < 40:
        problems.append("too short")
    if len(text.split()) > 450:
        problems.append("too long")
    if URL_RE.search(text):
        problems.append("contains a web address")
    if EMAIL_RE.search(text):
        problems.append("contains an email address")
    for m in LONG_NUMBER_RE.finditer(text):
        if _digit_count(m.group()) >= 5:
            problems.append("contains a long number")
            break
    if BANNED_RE.search(text):
        problems.append("breaks character or mentions police")
    if SENT_RE.search(text):
        problems.append("claims to have sent money")
    return problems


def tidy(text):
    """Strip things models like to add: subject lines, markdown, quoted history."""
    text = (text or "").strip()
    text = re.sub(r"(?im)^\s*subject\s*:.*$\n?", "", text)
    text = re.sub(r"(?m)^>.*$\n?", "", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"(?m)^#+\s*", "", text)
    text = re.sub(r"(?s)\n-{3,}.*$", "", text)  # anything after a divider
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


FALLBACK = """Hello again,

I sat down to answer you properly and Doug knocked the coffee into the keyboard, so I am typing this one
letter at a time on the library computer with a lady breathing down my neck about her turn.

I want to do this right. Could you write the steps out again, slow, like you would for a fellow who
still has a flip phone? Number them for me please, small numbers, I get lost.

Your friend,
Uncle Vern"""


def write_letter(llm, messages, attempts=3):
    """Ask the model for a letter until one passes the check. Returns (text, problems_seen)."""
    seen = []
    for _ in range(attempts):
        raw = llm.chat(messages)
        text = tidy(raw)
        problems = check_letter(text)
        if not problems:
            return text, seen
        seen.extend(problems)
        messages = messages + [
            {"role": "assistant", "content": text},
            {"role": "user", "content": "Rewrite that letter. It broke these rules: " + ", ".join(problems)
             + ". Stay in character as Vern."},
        ]
    return FALLBACK, seen
