"""Scammer letters go on the public page only after this."""
import os
import re

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
URL_RE = re.compile(r"(?:https?://|www\.)\S+|\b[a-z0-9-]+\.(?:com|net|org|io|co|info|biz|ru|xyz|me|ly|app|link)(?:/\S*)?\b", re.I)
PHONE_RE = re.compile(r"\+?\d[\d\s().\-]{6,}\d")
NUMBER_RE = re.compile(r"\b\d{4,}\b")
TITLE_NAME_RE = re.compile(r"\b(Mr|Mrs|Ms|Miss|Dr|Barrister|Prof|Rev|Sir|Engr|Chief)\.?\s+([A-Z][a-zA-Z'\-]+(?:\s+[A-Z][a-zA-Z'\-]+){0,2})")
SIGN_OFF_RE = re.compile(r"(?im)^(regards|best regards|yours (?:faithfully|sincerely|truly)|sincerely|thanks|thank you),?\s*\n+\s*(.+)$")
QUOTED_RE = re.compile(r"(?s)\n\s*On .{5,200}wrote:\s*\n.*$")
# "Dear Priya," names whoever the scam was sent to: the boss, or a friend who forwarded it.
GREETING_RE = re.compile(r"(?im)^([ \t]*(?:dear|hello|hi|hey|attention|attn|greetings|good day)[ \t]+)"
                         r"([^\n,:!.]{2,40}?)([ \t]*[,:!.\n])")
GENERIC = {"friend", "friends", "sir", "madam", "sir/madam", "sir/ma", "beneficiary", "customer", "user", "all",
           "there", "colleague", "partner", "recipient", "valued", "esteemed", "beloved", "winner", "student",
           "applicant", "candidate", "owner", "client", "member", "account", "holder", "in", "christ", "the",
           "and", "or", "my", "dear", "to", "you", "team", "everyone", "good", "day", "morning", "afternoon",
           "evening", "talent", "intern", "aspirant", "director", "manager", "ceo"}


def _greeting(m):
    words = re.findall(r"[a-z/]+", m.group(2).lower())
    # Scammers' replies say "Dear Vern" or "Hello Uncle Vern": Uncle's own made-up names stay.
    if words and all(w in GENERIC or w in {"uncle", "mr", "grandpa"} or w.title() in CAST for w in words):
        return m.group(0)
    return m.group(1) + bar(m.group(2)) + m.group(3)
BLOCK_CHAR = "█"
BLOCK = BLOCK_CHAR * 3


def bar(s):
    """A black bar about as long as what it hides, so the page can draw a real redaction."""
    return BLOCK_CHAR * max(3, min(22, len(s)))


def owner_words():
    """The owner's own words (REDACT_WORDS, comma separated: their name, college, employer)."""
    return [w for w in (w.strip() for w in os.environ.get("REDACT_WORDS", "").split(",")) if len(w) > 2]


def private(text):
    """Black out the owner's own words. Safe for Uncle's letters too, which otherwise go up as written."""
    for w in owner_words():
        text = re.sub(re.escape(w), lambda m: bar(m.group()), text or "", flags=re.I)
    return text or ""


TITLES = {"mr", "mrs", "ms", "miss", "dr", "barrister", "prof", "rev", "sir", "engr", "chief"}
NAME_RE = re.compile(r"[A-Z][a-zA-Z'.\-]+(?:\s+[A-Z][a-zA-Z'.\-]+){0,3}")
# Uncle's own people, who are made up and stay on the page.
CAST = {"Vern", "Pickett", "June", "Dale", "Doug", "Darlene", "Marlene"}


def names_in(text):
    """Names a scammer goes by in a letter: after a title (Dr. X) or under the sign-off."""
    out = [m.group(2) for m in TITLE_NAME_RE.finditer(text or "")]
    out += [m.group(2).strip() for m in SIGN_OFF_RE.finditer(text or "") if NAME_RE.fullmatch(m.group(2).strip())]
    return out


def _titled(m):
    """Black out the name after a title (Dr. X), but not Uncle's own (Mr. Pickett)."""
    if m.group(2).split()[0] in CAST:
        return m.group(0)
    return m.group(0)[:m.start(2) - m.start(0)] + bar(m.group(2))


def hide_names(text, names=()):
    """Uncle's letters on the page: his words stay, the names the scammer goes by are blacked out,
    the same as in their own letters."""
    t = TITLE_NAME_RE.sub(_titled, private(text))
    for n in names:
        for part in re.split(r"\s+", n or ""):
            part = part.strip(".,;:")
            if len(part) > 2 and part.lower() not in TITLES and part not in CAST:
                t = re.sub(r"\b" + re.escape(part) + r"\b", lambda m: bar(m.group()), t)
    return t


def subject(text):
    """A scam's subject line, as the public page shows it."""
    return redact(text).replace("\n", " ")


def redact(text, names=()):
    if not text:
        return ""
    text = private(text)
    t = QUOTED_RE.sub("", text)
    t = re.sub(r"(?m)^>.*$\n?", "", t)
    t = EMAIL_RE.sub(lambda m: bar(m.group()), t)
    t = URL_RE.sub(lambda m: bar(m.group()), t)
    t = PHONE_RE.sub(lambda m: bar(m.group()), t)
    t = NUMBER_RE.sub(lambda m: bar(m.group()), t)
    t = TITLE_NAME_RE.sub(_titled, t)
    t = SIGN_OFF_RE.sub(lambda m: m.group(1) + ",\n" + bar(m.group(2)), t)
    t = GREETING_RE.sub(_greeting, t)
    for n in names:
        for part in [n] + [p for p in re.split(r"\s+", n or "") if len(p) > 2]:
            if part and len(part) > 2:
                t = re.sub(re.escape(part), lambda m: bar(m.group()), t, flags=re.I)
    return t.strip()
