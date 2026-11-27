"""Pull the original scam out of a forwarded email."""
import email
import email.policy
import email.utils
import html
import re

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")

FWD_MARKERS = [
    re.compile(r"-{2,}\s*Forwarded message\s*-{2,}", re.I),          # Gmail
    re.compile(r"Begin forwarded message:", re.I),                     # Apple Mail
    re.compile(r"-{2,}\s*Original Message\s*-{2,}", re.I),            # Outlook
    re.compile(r"^_{5,}\s*$\n^From:", re.I | re.M),                    # Outlook web
]

HEADER_RE = re.compile(r"^\s*\**\s*(From|Reply-To|Subject|Date|Sent|To|Cc)\s*:\**\s*(.*)$", re.I)


def addresses(text):
    seen = []
    for a in EMAIL_RE.findall(text or ""):
        a = a.strip(".").lower()
        if a not in seen:
            seen.append(a)
    return seen


def strip_html(s):
    s = re.sub(r"(?is)<(script|style).*?</\1>", " ", s or "")
    s = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</li>", "\n", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t\r\f\v]+", " ", s)
    return re.sub(r"\n\s*\n\s*\n+", "\n\n", s).strip()


def _clean(v):
    v = v.replace("*", "").strip()
    v = re.sub(r"\s*\[mailto:[^\]]+\]", "", v)
    return v


def _split_addr(v):
    name, addr = email.utils.parseaddr(_clean(v).replace("&lt;", "<").replace("&gt;", ">"))
    if not addr or "@" not in addr:
        found = addresses(v)
        addr = found[0] if found else ""
    return name.strip().strip('"'), addr.lower()


def parse_forward(text):
    """Parse an inline forward. Returns dict or None if no forward marker is found."""
    if not text:
        return None
    best = None
    for m in FWD_MARKERS:
        hit = m.search(text)
        if hit and (best is None or hit.start() < best[0]):
            # Outlook web's marker is a rule line followed by the From: header, so keep the header.
            body_from = hit.start() if m.pattern.startswith("^_") else hit.end()
            best = (hit.start(), body_from)
    if best is None:
        return None
    note_end, start = best
    rest = text[start:].lstrip("\n")
    if rest.startswith("_"):
        rest = rest.split("\n", 1)[1] if "\n" in rest else ""
    lines = rest.splitlines()
    out = {"from_name": "", "from_addr": "", "reply_to": "", "subject": "", "body": "", "note": text[:note_end].strip()}
    i = 0
    seen_header = False
    while i < len(lines):
        line = lines[i]
        m = HEADER_RE.match(line)
        if m:
            seen_header = True
            key, val = m.group(1).lower(), m.group(2)
            # Some clients wrap long header values onto the next line.
            while i + 1 < len(lines) and lines[i + 1].startswith((" ", "\t")) and not HEADER_RE.match(lines[i + 1]):
                i += 1
                val += " " + lines[i].strip()
            if key == "from":
                out["from_name"], out["from_addr"] = _split_addr(val)
            elif key == "reply-to":
                out["reply_to"] = _split_addr(val)[1]
            elif key == "subject":
                out["subject"] = _clean(val)
            i += 1
            continue
        if seen_header and not line.strip():
            i += 1
            break
        if not seen_header and not line.strip():
            i += 1
            continue
        if seen_header:
            break
        i += 1
    out["body"] = "\n".join(lines[i:]).strip()
    return out


def parse_eml(raw):
    """Parse a forwarded-as-attachment .eml (bytes or str)."""
    if isinstance(raw, str):
        raw = raw.encode("utf-8", "replace")
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    from_name, from_addr = email.utils.parseaddr(str(msg.get("From", "")))
    _, reply_to = email.utils.parseaddr(str(msg.get("Reply-To", "")))
    body = ""
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is not None:
        body = part.get_content()
        if part.get_content_type() == "text/html":
            body = strip_html(body)
    return {"from_name": from_name, "from_addr": from_addr.lower(), "reply_to": reply_to.lower(),
            "subject": str(msg.get("Subject", "")), "body": body.strip(), "note": ""}


def candidates(parsed, exclude):
    """Addresses the scammer might want a reply at, best guess first."""
    exclude = {e.lower() for e in exclude if e}
    order = []
    for a in [parsed.get("reply_to")] + addresses(parsed.get("body", "")) + [parsed.get("from_addr")]:
        if a and a not in exclude and a not in order and not a.endswith(("@agentmail.to", "@agentmail.test")):
            order.append(a)
    return order


def extract_scam(message, fetch_attachment, exclude):
    """From an AgentMail message (dict) find the forwarded scam.

    fetch_attachment(attachment_id) -> bytes. Returns parsed dict with 'candidates', or None.
    """
    for att in message.get("attachments") or []:
        ctype = (att.get("content_type") or "").lower()
        name = (att.get("filename") or "").lower()
        if ctype == "message/rfc822" or name.endswith(".eml"):
            try:
                raw = fetch_attachment(att["attachment_id"])
            except Exception:  # noqa: BLE001  (the Fly connector blocks attachment downloads)
                raw = None
            if raw:
                parsed = parse_eml(raw)
                parsed["source"] = "eml"
                parsed["candidates"] = candidates(parsed, exclude)
                return parsed
    text = message.get("text") or ""
    if not text and message.get("html"):
        text = strip_html(message["html"])
    parsed = parse_forward(text)
    if parsed is None and message.get("html"):
        parsed = parse_forward(strip_html(message["html"]))
    if parsed is None:
        return None
    parsed["source"] = "inline"
    parsed["candidates"] = candidates(parsed, exclude)
    return parsed
