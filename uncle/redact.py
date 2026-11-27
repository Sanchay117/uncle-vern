"""Scammer letters go on the public page only after this."""
import re

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
URL_RE = re.compile(r"(?:https?://|www\.)\S+|\b[a-z0-9-]+\.(?:com|net|org|io|co|info|biz|ru|xyz|me|ly|app|link)(?:/\S*)?\b", re.I)
PHONE_RE = re.compile(r"\+?\d[\d\s().\-]{6,}\d")
NUMBER_RE = re.compile(r"\b\d{4,}\b")
TITLE_NAME_RE = re.compile(r"\b(Mr|Mrs|Ms|Miss|Dr|Barrister|Prof|Rev|Sir|Engr|Chief)\.?\s+([A-Z][a-zA-Z'\-]+(?:\s+[A-Z][a-zA-Z'\-]+){0,2})")
SIGN_OFF_RE = re.compile(r"(?im)^(regards|best regards|yours (?:faithfully|sincerely|truly)|sincerely|thanks|thank you),?\s*\n+\s*(.+)$")
QUOTED_RE = re.compile(r"(?s)\n\s*On .{5,200}wrote:\s*\n.*$")
BLOCK_CHAR = "█"
BLOCK = BLOCK_CHAR * 3


def bar(s):
    """A black bar about as long as what it hides, so the page can draw a real redaction."""
    return BLOCK_CHAR * max(3, min(22, len(s)))


def redact(text, names=()):
    if not text:
        return ""
    t = QUOTED_RE.sub("", text)
    t = re.sub(r"(?m)^>.*$\n?", "", t)
    t = EMAIL_RE.sub(lambda m: bar(m.group()), t)
    t = URL_RE.sub(lambda m: bar(m.group()), t)
    t = PHONE_RE.sub(lambda m: bar(m.group()), t)
    t = NUMBER_RE.sub(lambda m: bar(m.group()), t)
    t = TITLE_NAME_RE.sub(lambda m: m.group(0)[:m.start(2) - m.start(0)] + bar(m.group(2)), t)
    t = SIGN_OFF_RE.sub(lambda m: m.group(1) + ",\n" + bar(m.group(2)), t)
    for n in names:
        for part in [n] + [p for p in re.split(r"\s+", n or "") if len(p) > 2]:
            if part and len(part) > 2:
                t = re.sub(re.escape(part), lambda m: bar(m.group()), t, flags=re.I)
    return t.strip()
