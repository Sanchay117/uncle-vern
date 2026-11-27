"""Share cards: a 1200x630 PNG of Uncle's latest letter, for link previews on X, Discord and Slack.

Pillow is optional. Without it there are no cards and the pages simply carry no preview image.
"""
import io
import os
import re
import textwrap

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # pragma: no cover - depends on the box
    Image = None

W, H = 1200, 630
TABLE, PAPER, INK, SOFT = "#e9dfcb", "#fbf7ee", "#1d1a16", "#6c6357"
RED, BLUE, RULE, MARGIN = "#b8321f", "#23468c", "#c9d7ea", "#e7a3a3"
FONT_DIR = os.path.join(os.path.dirname(__file__), "fonts")
BARS = re.compile("(█+)")


def available():
    return Image is not None and os.path.exists(os.path.join(FONT_DIR, "CourierPrime-Regular.ttf"))


def _font(name, size, weight=None):
    f = ImageFont.truetype(os.path.join(FONT_DIR, name), size)
    if weight:
        try:
            f.set_variation_by_axes([weight])
        except (OSError, AttributeError):
            pass
    return f


def _airmail(d, y0, h):
    """The red and blue diagonal envelope edge."""
    for x in range(-h, W + h, 60):
        for off, col in ((0, RED), (30, BLUE)):
            a = x + off
            d.polygon([(a, y0 + h), (a + 18, y0 + h), (a + 18 + h, y0), (a + h, y0)], fill=col)


def _wrap(text, width, max_lines):
    """Monospace wrap that keeps paragraph breaks and ends a cut letter with '...'."""
    lines = []
    for para in re.split(r"\n\s*\n", (text or "").strip()):
        para = " ".join(para.split())
        if not para:
            continue
        if lines:
            lines.append("")
        lines.extend(textwrap.wrap(para, width) or [""])
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        while lines and not lines[-1]:
            lines.pop()
        last = lines[-1] if lines else ""
        if len(last) > width - 3:
            last = last[:width - 3].rsplit(" ", 1)[0]
        lines[-1] = last.rstrip(".,;:") + "..."
    return lines


def _draw_line(d, x, y, line, font, cw, fill):
    """Draw one line; runs of redaction blocks become solid black bars."""
    for part in BARS.split(line):
        if not part:
            continue
        if part[0] == "█":
            d.rectangle([x, y + 4, x + cw * len(part), y + 24], fill=INK)
        else:
            d.text((x, y), part, font=font, fill=fill)
        x += cw * len(part)


def _paper(letter):
    """Uncle's letter on ruled notepad paper, tipped a little."""
    pw, ph = 500, 520
    p = Image.new("RGBA", (pw, ph), PAPER)
    d = ImageDraw.Draw(p)
    for y in range(116, ph, 30):
        d.line([(0, y), (pw, y)], fill=RULE, width=1)
    d.line([(52, 0), (52, ph)], fill=MARGIN, width=2)
    d.text((70, 30), "Uncle Vern wrote:", font=_font("Caveat-wght.ttf", 38, 700), fill=BLUE)
    mono = _font("CourierPrime-Regular.ttf", 20)
    cw = mono.getlength("M")
    for i, line in enumerate(_wrap(letter, int((pw - 90) // cw), 14)):
        _draw_line(d, 70, 92 + i * 30, line, mono, cw, INK)
    shadow = Image.new("RGBA", (pw + 40, ph + 40), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rectangle([24, 30, pw + 24, ph + 30], fill=(0, 0, 0, 46))
    shadow.alpha_composite(p, (12, 12))
    return shadow.rotate(2.2, resample=Image.BICUBIC, expand=True)


def _postmark(pct, word):
    s = 190
    m = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(m)
    col = (184, 50, 31, 225)
    d.ellipse([6, 6, s - 6, s - 6], outline=col, width=6)
    d.ellipse([20, 20, s - 20, s - 20], outline=col, width=3)
    d.text((s / 2, 70), word, font=_font("CourierPrime-Regular.ttf", 24), fill=col, anchor="mm")
    d.text((s / 2, 112), f"{pct}%", font=_font("LibreCaslonText-wght.ttf", 50, 700), fill=col, anchor="mm")
    return m.rotate(14, resample=Image.BICUBIC)


def _lines(d, text, font, width):
    """Wrap text to a pixel width."""
    lines = [""]
    for w in text.split():
        trial = (lines[-1] + " " + w).strip()
        if not lines[-1] or d.textlength(trial, font=font) <= width:
            lines[-1] = trial
        else:
            lines.append(w)
    return lines


LEFT, TEXT_W, TOP, BOTTOM = 64, 440, 104, 528


def _layout(d, title, facts):
    """Title and facts for the left column: the biggest title that leaves room for the facts."""
    small = _font("LibreCaslonText-wght.ttf", 25)
    fact_lines = []
    for f in facts[:4]:
        lines = _lines(d, f, small, TEXT_W)
        if len(lines) > 2:
            lines = lines[:2]
            lines[1] = lines[1].rsplit(" ", 1)[0].rstrip(".,;:") + "..."
        fact_lines.append(lines)
    for keep in range(len(fact_lines), -1, -1):
        facts_h = sum(34 * len(f) + 6 for f in fact_lines[:keep])
        for size in (60, 54, 48, 44, 40, 36):
            tf = _font("LibreCaslonText-wght.ttf", size, 700)
            tl = _lines(d, title, tf, 530)
            if TOP + len(tl) * int(size * 1.22) + 18 + facts_h <= BOTTOM:
                return tf, tl, small, fact_lines[:keep]
    tl = tl[:4]
    tl[-1] = tl[-1].rstrip(".,;:") + "..."
    return tf, tl, small, []


def render(title, letter, facts, url, pct=None, stamp="SCAM", label="UNCLE VERN'S MAILBAG"):
    """title: big words on the left. letter: Uncle's letter (already redacted). facts: short lines.
    url: shown at the bottom. pct: the decision model's number for the red stamp, or None."""
    img = Image.new("RGBA", (W, H), TABLE)
    d = ImageDraw.Draw(img)
    _airmail(d, 0, 16)
    _airmail(d, H - 16, 16)

    d.text((LEFT, 60), label, font=_font("CourierPrime-Regular.ttf", 24), fill=RED)
    tf, tl, small, fact_lines = _layout(d, title, facts)
    y = TOP
    for line in tl:
        d.text((LEFT, y), line, font=tf, fill=INK)
        y += int(tf.size * 1.22)
    y += 18
    for lines in fact_lines:
        for line in lines:
            d.text((LEFT, y), line, font=small, fill=SOFT)
            y += 34
        y += 6
    d.text((LEFT, H - 76), url, font=_font("CourierPrime-Regular.ttf", 22), fill=BLUE)

    paper = _paper(letter)
    img.alpha_composite(paper, (W - paper.width - 26, 34))
    if pct is not None:
        # Franked over the corner of the letter and the envelope's edge, clear of the words.
        img.alpha_composite(_postmark(pct, stamp), (W - paper.width - 112, H - 200))
    out = io.BytesIO()
    img.convert("RGB").save(out, "PNG", optimize=True)
    return out.getvalue()
