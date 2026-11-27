"""The public page: Uncle's kitchen table.

Look and feel borrows ideas (not code) from the user's UI library: the crumpled office
paper and black redaction bars of las6's [REDACTED] study, the typing cadence of
React Bits' Text Type, and the mechanical roll of netoun's split-flap board, here as
the odometer of Uncle's Buick.
"""
import html
import re
import time
import urllib.parse

from . import redact
from .engine import ASK_WORDS, FRUSTRATION, jev_of


def esc(s):
    return html.escape(str(s if s is not None else ""), quote=True)


def dur(s):
    s = max(0, float(s or 0))
    if s < 10:
        return f"{s:.1f} s"
    if s < 60:
        return f"{int(s)} s"
    m, sec = divmod(int(s), 60)
    if m < 60:
        return f"{m} m {sec} s"
    h, m = divmod(m, 60)
    if h < 48:
        return f"{h} h {m} m"
    d, h = divmod(h, 24)
    return f"{d} d {h} h"


def ago(t):
    if not t:
        return ""
    return dur(time.time() - t) + " ago"


def num(n):
    return f"{int(n or 0):,}"


SCAM_LABEL = {
    "advance_fee": "Inheritance / prize", "tech_support": "Fake renewal", "romance": "Romance",
    "job": "Easy money job", "investment": "Crypto pitch", "phishing": "Phishing",
    "extortion": "Blackmail", "probe": "Address check", "other": "Other",
}


# Who is answering, set by the server at start. Decisions: Jev (TypeSafe), Claude (Anthropic) or
# Clef (Ollama). Letters: Ollama or Claude.
DECIDER = {"name": "Jev", "maker": "TypeSafe", "about": "TypeSafe's decision model"}
VOICE = {"name": "Ollama", "maker": "Ollama Cloud"}


def dn():
    return DECIDER["name"]


def dmaker():
    return DECIDER["maker"]


def dabout():
    return DECIDER.get("about") or f"{dmaker()}'s decision model"


def vn():
    return VOICE["name"]


def connectors_line():
    """'TypeSafe (Jev for every decision), Anthropic (Claude for his voice)'; merged when one maker does both."""
    def key(maker):
        return "Ollama Cloud" if maker.startswith("Ollama") else maker

    jobs = {}
    jobs.setdefault(key(dmaker()), []).append((dn(), "every decision"))
    jobs.setdefault(key(VOICE["maker"]), []).append((vn(), "his voice"))
    parts = []
    for maker, items in jobs.items():
        names = {n for n, _ in items if n not in maker}
        if len(items) > 1 and len(names) == 1 and all(n not in maker for n, _ in items):
            inner = f"{items[0][0]} for " + " and ".join(j for _, j in items)
        else:
            inner = ", and ".join(j if n in maker else f"{n} for {j}" for n, j in items)
        parts.append(f"{maker} ({inner})")
    return ", ".join(parts)


WANTS = ASK_WORDS


def _svg_uri(svg):
    return "data:image/svg+xml," + urllib.parse.quote(re.sub(r"\s+", " ", svg).strip(), safe="/:=' ,.#()-")


CRUMPLE = _svg_uri("""<svg xmlns='http://www.w3.org/2000/svg' width='700' height='700'>
<filter id='c' x='0' y='0'><feTurbulence type='fractalNoise' baseFrequency='.011' numOctaves='5' seed='11'/>
<feDiffuseLighting lighting-color='#ffffff' surfaceScale='2.4'><feDistantLight azimuth='225' elevation='58'/>
</feDiffuseLighting></filter><rect width='100%' height='100%' filter='url(#c)'/></svg>""")

GRAIN = _svg_uri("""<svg xmlns='http://www.w3.org/2000/svg' width='180' height='180'>
<filter id='n'><feTurbulence type='fractalNoise' baseFrequency='.85' numOctaves='2' stitchTiles='stitch'/>
<feColorMatrix values='0 0 0 0 .1  0 0 0 0 .08  0 0 0 0 .05  0 0 0 .55 -.18'/></filter>
<rect width='100%' height='100%' filter='url(#n)'/></svg>""")

FILTERS = """<svg width="0" height="0" style="position:absolute" aria-hidden="true">
<filter id="rough"><feTurbulence type="fractalNoise" baseFrequency=".06" numOctaves="2" seed="3"/>
<feDisplacementMap in="SourceGraphic" scale="2.6"/></filter>
<filter id="ink"><feTurbulence type="fractalNoise" baseFrequency=".9" numOctaves="1" seed="8" result="t"/>
<feColorMatrix in="t" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 -2.2 1.5" result="m"/>
<feComposite in="SourceGraphic" in2="m" operator="in"/></filter>
</svg>"""

CSS = """
:root{--table:#e9dfcb;--paper:#fbf7ee;--office:#e8e7e2;--ink:#1d1a16;--soft:#6c6357;--red:#b8321f;
  --blue:#23468c;--line:#d7cab0;--note:#f6e27a;--rule:#c9d7ea;--margin:#e7a3a3}
*{box-sizing:border-box}
html{background:var(--table)}
body{margin:0;color:var(--ink);font:17px/1.55 "Libre Caslon Text",Georgia,serif;background:var(--table)}
body::before{content:"";position:fixed;inset:0;pointer-events:none;z-index:50;background-image:url("%GRAIN%");opacity:.5}
.airmail{height:10px;background:repeating-linear-gradient(135deg,var(--red) 0 18px,var(--paper) 18px 30px,var(--blue) 30px 48px,var(--paper) 48px 60px)}
.wrap{max-width:1060px;margin:0 auto;padding:0 22px}
a{color:var(--blue)}
header.top{display:flex;justify-content:space-between;align-items:center;gap:16px;padding:16px 0 4px;flex-wrap:wrap}
.mark{font-weight:700;font-size:19px;color:inherit;text-decoration:none}
.mark span{color:var(--red)}
.awake{font:13px/1.3 "Courier Prime",ui-monospace,monospace;color:var(--soft);display:flex;align-items:center;gap:8px}
.awake i{width:9px;height:9px;border-radius:50%;background:#3d9a4b;box-shadow:0 0 0 4px rgba(61,154,75,.18);
  animation:breathe 2.6s ease-in-out infinite}
@keyframes breathe{50%{box-shadow:0 0 0 7px rgba(61,154,75,.05)}}

/* hero */
.hero{display:grid;grid-template-columns:1.1fr .9fr;gap:34px;align-items:center;padding:26px 0 18px}
h1{font-size:clamp(36px,5.6vw,64px);line-height:1.02;margin:6px 0 16px;letter-spacing:-.012em}
h1 em{font-style:italic;color:var(--red);white-space:nowrap}
.lede{font-size:20px;max-width:34em;margin:0 0 22px}
.lede b{font-weight:700}
.ctas{display:flex;gap:12px;flex-wrap:wrap}
.btn{display:inline-block;padding:12px 18px;border:2px solid var(--ink);background:var(--ink);color:var(--paper);
  text-decoration:none;font:600 15px/1 system-ui,sans-serif;border-radius:2px;cursor:pointer}
.btn:hover{background:#000}
.btn.ghost{background:transparent;color:var(--ink)}
.btn[disabled]{opacity:.6;cursor:wait}
.desk{position:relative;min-height:380px}
.desk .sheet{position:absolute;inset:18px 30px 0 10px;transform:rotate(-2.2deg);overflow:hidden}
.desk .sheet.under{transform:rotate(3deg);inset:6px 8px 20px 36px;filter:brightness(.97)}
.sticky{position:absolute;right:-6px;bottom:-14px;width:210px;padding:16px 16px 18px;background:var(--note);
  font:26px/1.05 "Caveat",cursive;color:#2b2414;transform:rotate(4deg);z-index:3;
  box-shadow:0 1px 0 rgba(255,255,255,.4) inset,0 14px 18px -12px rgba(0,0,0,.45)}
.sticky::after{content:"";position:absolute;left:38%;top:-9px;width:70px;height:20px;background:rgba(255,255,255,.55);transform:rotate(-3deg)}
.sticky small{display:block;text-align:right;margin-top:8px;font-size:22px}

/* papers */
.paper{position:relative;padding:26px 28px 24px;box-shadow:0 1px 1px rgba(0,0,0,.08),0 18px 30px -22px rgba(0,0,0,.55)}
.paper.office{background:var(--office) url("%CRUMPLE%");background-size:700px;background-blend-mode:multiply;
  font:15px/1.65 "Courier Prime",ui-monospace,monospace;color:#2a2925}
.paper.office::before{content:"";position:absolute;inset:0;background:linear-gradient(115deg,rgba(255,255,255,.35),rgba(255,255,255,0) 40%,rgba(0,0,0,.04));pointer-events:none}
.paper.notepad{background:
  linear-gradient(90deg,transparent 46px,var(--margin) 46px 47.5px,transparent 47.5px),
  repeating-linear-gradient(var(--paper) 0 27px,var(--rule) 27px 28px);
  background-color:var(--paper);background-position:0 0,0 -7px;padding:28px 26px 28px 66px;font:16px/28px "Courier Prime",ui-monospace,monospace}
.paper .body{white-space:pre-wrap;word-wrap:break-word}
.head{font:11px/1.3 system-ui,sans-serif;letter-spacing:.12em;text-transform:uppercase;color:var(--soft);
  border-bottom:1px solid rgba(0,0,0,.18);padding-bottom:8px;margin-bottom:14px;display:flex;justify-content:space-between;gap:8px}
.bar{display:inline-block;height:1.05em;vertical-align:-.17em;background:#141312;filter:url(#rough);margin:0 1px}
.stampmark{position:absolute;right:26px;top:-34px;z-index:2;color:var(--red);opacity:.82;transform:rotate(-11deg);filter:url(#ink);pointer-events:none}

/* ledger / odometer */
.ledger{display:grid;grid-template-columns:repeat(6,1fr);background:var(--paper);border:2px solid var(--ink);margin:30px 0 8px}
.ledger div{padding:14px 14px 12px;border-right:1px dashed var(--line)}
.ledger div:last-child{border-right:0}
.ledger .big{grid-column:1/-1;border-right:0;border-bottom:2px solid var(--ink);display:flex;align-items:baseline;
  flex-wrap:wrap;gap:4px 16px;padding:16px 16px 14px}
.ledger .big b{font-size:46px;color:var(--red)}.ledger .big small{margin:0;font-size:12px}
.share{margin:14px 0 0;font:15px/1.5 system-ui,sans-serif;color:var(--soft)}
.wakebox{margin:18px 0 6px}.wakes{display:block;width:100%;height:36px;color:var(--ink)}
.ticks{display:flex;justify-content:space-between;font:13px system-ui,sans-serif;color:var(--soft);margin:4px 0 0}
.wakes rect{fill:var(--ink)}.wakes text{font:13px system-ui,sans-serif;fill:var(--soft)}
.wakebox p{margin:6px 0 0;font:13px/1.45 system-ui,sans-serif;color:var(--soft)}
.ledger b{display:block;font-size:30px;line-height:1.05;font-weight:700;font-variant-numeric:tabular-nums;white-space:nowrap}
.ledger small{display:block;margin-top:6px;font:11px/1.3 system-ui,sans-serif;color:var(--soft);text-transform:uppercase;letter-spacing:.07em}
.odo{display:inline-flex;overflow:hidden;height:1.1em;line-height:1.1em}
.odo .col{display:inline-flex;flex-direction:column;transition:transform 1.4s cubic-bezier(.2,.8,.2,1)}
.odo .col span{height:1.1em}
.odo .sep{display:inline-block}
.foot-note{font:13px/1.45 system-ui,sans-serif;color:var(--soft);margin:6px 0 0;max-width:62em}

h2{font-size:30px;margin:54px 0 16px}
h2 small{font:13px/1.3 system-ui,sans-serif;color:var(--soft);margin-left:10px;letter-spacing:.02em}
@media (max-width:560px){h2 small{display:block;margin:6px 0 0}}
.replybox{margin-top:16px}.replybox textarea{min-height:110px}
.read{font:13px/1.5 system-ui,sans-serif;color:var(--soft);margin:12px 0 0}

/* mailbag */
.bag{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:20px}
.env{position:relative;background:var(--paper);border:1px solid var(--line);padding:20px 18px 16px;
  box-shadow:0 12px 22px -18px rgba(0,0,0,.5);text-decoration:none;color:inherit;display:block;transition:transform .15s}
.env:nth-child(odd){transform:rotate(-.6deg)}.env:nth-child(even){transform:rotate(.5deg)}
.env:hover{transform:translateY(-3px) rotate(0)}
.env::before{content:"";position:absolute;inset:0 0 auto 0;height:6px;
  background:repeating-linear-gradient(135deg,var(--red) 0 10px,transparent 10px 16px,var(--blue) 16px 26px,transparent 26px 32px)}
.tag{font:11px/1 system-ui,sans-serif;text-transform:uppercase;letter-spacing:.1em;color:var(--soft);margin-right:84px}
.env h3{margin:8px 84px 6px 0;font-size:19px;line-height:1.25}
.env .post{position:absolute;top:10px;right:8px}
.env p{margin:10px 0 0;font:14px/1.5 "Courier Prime",ui-monospace,monospace;color:#3d372f;
  display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;overflow:hidden}
.meter{display:flex;gap:3px;margin:10px 0 3px}
.meter i{flex:1;height:7px;background:var(--line);border-radius:1px}
.meter i.on{background:var(--red)}
.meta{font:13px/1.4 system-ui,sans-serif;color:var(--soft)}
.empty{background:var(--paper);border:1px dashed var(--line);padding:24px;font:22px/1.2 "Caveat",cursive}

/* try */
.bymail{margin:18px 0 0;padding:14px 18px;background:var(--paper);border:1px dashed var(--line);font-size:16px}
.try{display:grid;grid-template-columns:1fr 1fr;gap:26px;align-items:start}
.try textarea{width:100%;min-height:250px;font:15px/1.6 "Courier Prime",ui-monospace,monospace;padding:16px;
  border:0;background:var(--office) url("%CRUMPLE%");background-size:700px;background-blend-mode:multiply;color:var(--ink);
  box-shadow:0 18px 30px -22px rgba(0,0,0,.55);resize:vertical}
.try textarea:focus{outline:2px solid var(--blue);outline-offset:3px}
.typing::after{content:"\\258d";animation:blink 1s steps(1) infinite;color:var(--ink);margin-left:1px}
@keyframes blink{50%{opacity:0}}
.out .paper{min-height:250px}.out .paper.office{min-height:0;padding:18px 22px}
.wait{font:24px/1.2 "Caveat",cursive;color:var(--soft);padding:20px 0}

/* how + rules */
.steps{display:grid;grid-template-columns:repeat(3,1fr);gap:20px}
.card{background:var(--paper);padding:18px 18px 16px;border-top:3px solid var(--ink);box-shadow:0 12px 22px -18px rgba(0,0,0,.45)}
.card b{font:700 12px/1 system-ui,sans-serif;color:var(--red);letter-spacing:.1em}
.card h4{margin:6px 0 6px;font-size:19px}
.card p{margin:0;font-size:15.5px}
.rules{position:relative;margin:28px auto 0;max-width:640px;background:var(--note);padding:18px 22px 20px;transform:rotate(-1deg);
  font:25px/1.15 "Caveat",cursive;box-shadow:0 14px 18px -12px rgba(0,0,0,.4)}
.rules::after{content:"";position:absolute;left:44%;top:-10px;width:84px;height:22px;background:rgba(255,255,255,.55);transform:rotate(2deg)}

/* diary */
.diary{list-style:none;padding:12px 18px;margin:0;background:var(--paper);border:1px solid var(--line);
  font:14.5px/1.5 "Courier Prime",ui-monospace,monospace}
.diary li{padding:9px 0;border-bottom:1px dashed var(--line);display:grid;grid-template-columns:120px 1fr;gap:14px}
.diary li:last-child{border-bottom:0}
.diary time{color:var(--soft)}

/* thread */
.thread-head{padding:26px 0 6px}
.thread-head h1{font-size:clamp(28px,4.4vw,46px);max-width:24ch}
.conv{display:flex;flex-direction:column;gap:30px;margin:26px 0}
.conv .u{margin-right:14%}
.conv .s{margin-left:14%}
.conv .u .paper{transform:rotate(-.5deg)}
.conv .s .paper{transform:rotate(.6deg)}
.from{font:11px/1 system-ui,sans-serif;text-transform:uppercase;letter-spacing:.1em;color:var(--soft);margin:0 0 8px}
.asleep{font:24px/1.2 "Caveat",cursive;color:var(--soft);text-align:center}

/* footer scene */
.scene{display:block;width:100%;height:auto;margin:70px 0 0;color:var(--ink)}
footer{padding:18px 0 46px;border-top:2px solid var(--ink);font:14px/1.6 system-ui,sans-serif;color:var(--soft)}
footer a{color:var(--ink)}
footer b{color:var(--ink)}

@media (max-width:860px){.hero,.try{grid-template-columns:1fr}.desk{min-height:340px;margin-top:10px}
  .ledger{grid-template-columns:repeat(3,1fr)}.ledger div:nth-child(4){border-right:0}
  .ledger div:nth-child(n+2):nth-child(-n+4){border-bottom:1px dashed var(--line)}.steps{grid-template-columns:1fr}}
@media (max-width:560px){body{font-size:16px}.lede{font-size:18px}.ledger{grid-template-columns:repeat(2,1fr)}
  .ledger div{border-right:0!important;border-bottom:1px dashed var(--line)}.ledger b{font-size:25px}
  .diary li{grid-template-columns:1fr;gap:2px}.conv .u,.conv .s{margin:0}.sticky{width:170px;font-size:22px}
  .paper.notepad{padding-left:52px;background:linear-gradient(90deg,transparent 36px,var(--margin) 36px 37.5px,transparent 37.5px),
  repeating-linear-gradient(var(--paper) 0 27px,var(--rule) 27px 28px);background-color:var(--paper);background-position:0 0,0 -7px}}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
""".replace("%CRUMPLE%", CRUMPLE).replace("%GRAIN%", GRAIN)

FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
         '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
         '<link href="https://fonts.googleapis.com/css2?family=Caveat:wght@500&family=Courier+Prime&'
         'family=Libre+Caslon+Text:ital,wght@0,400;0,700;1,400&display=swap" rel="stylesheet">')

# Vern's street, left to right: his house, the mailbox (flag up: a letter came), Doug the ferret,
# the Buick he keeps mentioning, and the town sign. Labels are handwritten so nobody has to guess.
SCENE = """<svg class="scene" viewBox="0 0 1000 175" fill="none" stroke="currentColor" stroke-width="2"
 stroke-linecap="round" stroke-linejoin="round" role="img" aria-label="Vern's street: his house, his mailbox
 with the flag up, Doug the ferret, his Buick and the Tillman's Ford town sign">
<g font-family="Caveat,cursive" font-size="25" fill="currentColor" stroke="none" opacity=".75" text-anchor="middle">
<text x="150" y="34">Vern's place</text><text x="268" y="62">mail's here</text>
<text x="498" y="100">Doug</text><text x="712" y="58">the Buick</text></g>
<path d="M0 150 H1000" />
<path d="M100 150 V96 L150 60 L200 96 V150" /><path d="M90 103 L150 56 L210 103" stroke="#b8321f" stroke-width="3"/>
<rect x="128" y="114" width="22" height="36" /><rect x="163" y="104" width="22" height="18" />
<path d="M174 104 V122 M163 113 H185" /><path d="M182 74 V48 H194 V82" />
<path d="M262 150 V114" /><path d="M244 114 V104 Q244 96 252 96 H276 Q284 96 284 104 V114 Z" />
<path d="M284 106 H291 V82 H303 V91 H291" stroke="#b8321f" stroke-width="2.5"/>
<path d="M330 150 V124 M355 150 V124 M380 150 V124 M405 150 V124 M322 132 H413 M322 142 H413" />
<ellipse cx="498" cy="137" rx="30" ry="7.5" fill="var(--table)" />
<circle cx="532" cy="132" r="7" fill="var(--table)" /><path d="M529 125.5 l2 -4 l3 3.5" />
<circle cx="535" cy="131" r="1" fill="currentColor" stroke="none" /><circle cx="539.5" cy="134" r="1.2" fill="currentColor" stroke="none" />
<path d="M469 135 C458 130 452 124 444 127" /><path d="M478 143 V150 M488 144 V150 M508 144 V150 M518 143 V150" />
<path d="M600 138 V121 Q600 113 609 112 L652 108 L674 88 L752 88 L774 107 L812 110 Q822 111 822 121 V138
 H802 A17 17 0 0 0 768 138 H662 A17 17 0 0 0 628 138 Z" fill="var(--table)" />
<path d="M680 106 L692 94 L716 94 L716 106 Z M722 106 L722 94 L746 94 L760 106 Z" />
<path d="M606 122 H816" stroke-width="1.5" /><circle cx="607" cy="117" r="2.5" />
<circle cx="645" cy="138" r="12" fill="var(--table)" /><circle cx="645" cy="138" r="4" />
<circle cx="785" cy="138" r="12" fill="var(--table)" /><circle cx="785" cy="138" r="4" />
<path d="M922 150 V106" /><rect x="848" y="64" width="148" height="42" rx="3" fill="var(--table)" />
<g font-family="'Courier Prime',monospace" fill="currentColor" stroke="none" text-anchor="middle">
<text x="922" y="83" font-size="13.5" font-weight="700" textLength="128" lengthAdjust="spacingAndGlyphs">TILLMAN'S FORD</text>
<text x="922" y="99" font-size="12">pop. 812</text></g>
</svg>"""


# An airmail envelope with a red stamp, to match the stripe across the top of every page.
FAVICON = "data:image/svg+xml," + urllib.parse.quote(re.sub(r"\s+", " ", """<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'>
<rect x='4' y='14' width='56' height='38' rx='5' fill='#f6efe1' stroke='#1f1b16' stroke-width='4'/>
<path d='M6 17 L32 37 L58 17' fill='none' stroke='#1f1b16' stroke-width='4' stroke-linejoin='round'/>
<rect x='41' y='22' width='12' height='14' fill='#b8321f'/>
<path d='M6 48 l6 -6 M14 50 l6 -6 M22 50 l6 -6' stroke='#2b4c8c' stroke-width='3'/></svg>""").strip(), safe="")


def page(title, body, desc="Uncle Vern answers scam emails, at length, so scammers waste their time on him.",
         image=None, url=None):
    share = ""
    if image:
        share = (f'<meta property="og:image" content="{esc(image)}"><meta property="og:image:width" content="1200">'
                 f'<meta property="og:image:height" content="630"><meta name="twitter:card" content="summary_large_image">'
                 f'<meta name="twitter:image" content="{esc(image)}">')
    if url:
        share += f'<meta property="og:url" content="{esc(url)}"><meta property="og:type" content="website">'
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title><meta name="description" content="{esc(desc)}">
<meta property="og:title" content="{esc(title)}"><meta property="og:description" content="{esc(desc)}">{share}
<meta name="theme-color" content="#e9dfcb"><link rel="icon" href="{FAVICON}">
{FONTS}<style>{CSS}</style></head><body>{FILTERS}<div class="airmail"></div><div class="wrap">{body}</div>
<script>{ODO_JS}</script></body></html>"""


BAR_RE = re.compile("█+")


def letter_body(text):
    """Escape a letter and turn redaction runs into drawn black bars."""
    out = []
    last = 0
    for m in BAR_RE.finditer(text or ""):
        out.append(esc(text[last:m.start()]))
        n = len(m.group())
        out.append(f'<span class="bar" style="width:{n * 0.6:.1f}em" title="blacked out"></span>')
        last = m.end()
    out.append(esc((text or "")[last:]))
    return "".join(out)


def postmark(pct, top="SCAM", bottom=None, size=74):
    """A round red rubber stamp with the decision model's number in the middle."""
    bottom = bottom or dn().upper()
    r = size / 2 - 3
    c = size / 2
    return f"""<svg class="post" width="{size + 30}" height="{size}" viewBox="0 0 {size + 30} {size}" aria-label="{dn()} {pct}% {top.lower()}">
<g stroke="#b8321f" fill="none" stroke-width="1.6" opacity=".85" transform="rotate(-12 {c} {c})">
<circle cx="{c}" cy="{c}" r="{r}" stroke-width="2.2"/><circle cx="{c}" cy="{c}" r="{r - 6}"/>
<path d="M{size - 2} {c - 12} q6 -4 12 0 t12 0 M{size - 2} {c - 4} q6 -4 12 0 t12 0 M{size - 2} {c + 4} q6 -4 12 0 t12 0 M{size - 2} {c + 12} q6 -4 12 0 t12 0"/>
<text x="{c}" y="{c + 6}" text-anchor="middle" fill="#b8321f" stroke="none" font-family="system-ui,sans-serif" font-weight="800" font-size="{size * 0.24:.0f}">{pct}%</text>
<text x="{c}" y="{c - 11}" text-anchor="middle" fill="#b8321f" stroke="none" font-family="system-ui,sans-serif" font-weight="700" font-size="7.5" letter-spacing="1.2">{esc(top)}</text>
<text x="{c}" y="{c + 19}" text-anchor="middle" fill="#b8321f" stroke="none" font-family="system-ui,sans-serif" font-weight="700" font-size="7.5" letter-spacing="1.2">{esc(bottom)}</text>
</g></svg>"""


def awake_line(m):
    this = m.get("this_wake_s")
    slept = m.get("slept_s")
    if this is None:
        return "Awake"
    bit = f"Woke up {dur(this)} ago"
    if slept and slept > 20:
        bit += f" after {dur(slept)} asleep"
    return bit + ". He nods off again when it goes quiet."


def frustration_meter(v):
    v = float(v or 0)
    cells = "".join(f'<i class="{"on" if v >= i + 0.5 else ""}"></i>' for i in range(5))
    label = FRUSTRATION[min(4, max(0, int(round(v))))]
    return f'<div class="meter" title="{dn()} frustration score {v:.1f} of 4">{cells}</div>' \
           f'<div class="meta">Scammer\'s mood, per {dn()}: {esc(label.lower())} ({v:.1f} of 4)</div>'


def header(m):
    return f"""<header class="top"><a class="mark" href="/">Uncle Vern<span>.</span></a>
<div class="awake"><i></i>{esc(awake_line(m))}</div></header>"""


def odo(n):
    return f'<span class="odo-num" data-v="{int(n or 0)}">{num(n)}</span>'


def thread_card(t, letters):
    uncle = [l for l in letters if l["direction"] == "uncle"]
    them = [l for l in letters if l["direction"] == "scammer"]
    last = (letters[-1]["public_body"] if letters else t["draft"]) or ""
    who = "Uncle" if letters and letters[-1]["direction"] == "uncle" else "Scammer"
    if t["status"] == "closed":
        state = f"Closed: {t['close_reason'] or ''}"
    elif them:
        state = f"{len(them)} letters back · last {ago(t['last_scammer_at'])}"
    else:
        state = f"Letter sent {ago(t['approved_at'])} · waiting for a bite"
    fr = frustration_meter(t["frustration"]) if them else ""
    return f"""<a class="env" href="/t/{t['id']}">{postmark(round((t['scam_prob'] or 0) * 100))}
<div class="tag">{esc(SCAM_LABEL.get(t['scam_type'], 'Scam'))}</div>
<h3>{esc((redact.subject(t['scam_subject']) or 'A letter')[:80])}</h3>
<div class="meta">{esc(state)} · {len(uncle)} from Uncle</div>
{fr}
<p><b>{who}:</b> {letter_body(last[:400])}</p></a>"""


def wake_strip(wakes, now, hours=24):
    """Uncle's last day as a strip: an ink mark for each stretch he was awake, a dotted line where he slept.

    wakes: rows with started_at and last_seen (the meter's heartbeat), any order."""
    span = hours * 3600
    start = now - span

    def x(t):
        return 10 + 980 * (max(start, min(now, t)) - start) / span

    marks, awake = [], 0
    for w in wakes:
        a = w["started_at"]
        b = max(w["last_seen"] or a, a)
        if b < start or a > now:
            continue
        awake += min(b, now) - max(a, start)
        marks.append(f'<rect x="{x(a):.1f}" y="4" width="{max(3.0, x(b) - x(a)):.1f}" height="28"/>')
    # Labels in HTML, not the SVG, so they stay readable when the strip shrinks to a phone's width.
    ticks = "".join(f'<span>{"now" if h == 0 else f"{h} h ago"}</span>' for h in range(hours, -1, -6))
    return f"""<div class="wakebox"><svg class="wakes" viewBox="0 0 1000 36" preserveAspectRatio="none" role="img"
 aria-label="Uncle's last {hours} hours: {len(marks)} times awake, asleep the rest">
<path d="M10 18 H990" stroke="currentColor" stroke-width="1.5" stroke-dasharray="2 6" vector-effect="non-scaling-stroke"/>{''.join(marks)}</svg>
<div class="ticks">{ticks}</div>
<p><b>Uncle's last {hours} hours.</b> Each mark is a stretch he was awake: a letter came in, someone tried him,
or he was looked in on. Awake {esc(dur(awake)) if awake else "0 s"} in all, over {len(marks)} wake-up{"" if len(marks) == 1 else "s"}; asleep the rest.</p></div>"""


READ_WPM, WRITE_WPM = 200, 25


def wasted_tile(wasted, totals):
    if wasted:
        return f'<div class="big"><b>{esc(dur(wasted))}</b><small>Scammer time wasted (est.)</small></div>'
    n = totals.get("uncle_letters") or 0
    return (f'<div class="big"><b>{n} letter{"" if n == 1 else "s"} in the mail</b><small>Waiting on the first '
            'scammer to write back. The time-wasted clock starts then.</small></div>')


def wasted_seconds(totals):
    """A scammer's time spent on Uncle: reading his letters (only where they wrote back, so we know they
    read them) at READ_WPM, plus writing their own at WRITE_WPM, a typical pace for composing an email."""
    return round(60 * ((totals.get("uncle_words_read") or 0) / READ_WPM
                       + (totals.get("scammer_words") or 0) / WRITE_WPM))


def rough(s):
    """A spoken-aloud duration for the share card: 'about 12 minutes'."""
    s = float(s or 0)
    if s < 90:
        return "about a minute"
    if s < 5400:
        return f"about {round(s / 60)} minutes"
    return f"about {s / 3600:.1f} hours".replace(".0 ", " ")


def host(cfg):
    return re.sub(r"^https?://", "", cfg.public_url)


def thread_share(cfg, t, letters):
    """What the share card for one conversation says."""
    mine = [l for l in letters if l["direction"] == "uncle" and l["public_body"]]
    theirs = [l for l in letters if l["direction"] == "scammer"]
    subject = redact.subject(t["scam_subject"]) or ""
    title = f"Uncle Vern vs. \u201c{subject}\u201d" if subject else "Uncle Vern vs. a scammer"
    facts = [f"{SCAM_LABEL.get(t['scam_type'], 'Scam')} scam"]
    if t["status"] == "closed":
        facts.append(f"Closed: {t['close_reason'] or 'done'}")
    elif t["first_bite_at"]:
        facts.append(f"On the hook for {rough((t['last_scammer_at'] or 0) - (t['approved_at'] or 0))}")
    else:
        facts.append("Waiting for the scammer to write back")
    facts.append(f"{len(mine)} letter{'' if len(mine) == 1 else 's'} from Uncle, {len(theirs)} back")
    if theirs:
        read = sum(l["words"] or 0 for l in mine)
        wasted = wasted_seconds({"uncle_words_read": read, "scammer_words": sum(l["words"] or 0 for l in theirs)})
        facts.append(f"{rough(wasted).capitalize()} of their time wasted")
    return {"title": title, "letter": mine[-1]["public_body"] if mine else "", "facts": facts,
            "url": f"{host(cfg)}/t/{t['id']}", "pct": round((t["scam_prob"] or 0) * 100),
            "label": "UNCLE VERN'S MAILBAG"}


SAMPLE_LETTER = """Dear Sir or Madam,

I got your letter about the money and I would surely like it. My late wife June did the checkbook so you will have to be patient with me. My nephew Dale says I should not write back to strangers but you seem like a fine young man.

Now which Western Union is it you want? There is one by the Piggly Wiggly but they close at four on Tuesdays.

Yours truly,
Vern"""


def home_share(cfg, totals, latest_uncle=None):
    wasted = wasted_seconds(totals)
    facts = ["Forward him a scam and he writes back."]
    if totals.get("approached"):
        facts.append(f"{totals['approached']} scammer{'' if totals['approached'] == 1 else 's'} written to, "
                     f"{totals.get('bit') or 0} wrote back")
    if wasted:
        facts.append(f"{rough(wasted).capitalize()} of scammer time wasted")
    return {"title": "Uncle Vern answers scam emails. All of them. At length.",
            "letter": (latest_uncle or {}).get("public_body") or SAMPLE_LETTER, "facts": facts,
            "url": host(cfg), "pct": None, "label": "A SCAMBAITER ON A FLY.IO SPRITE"}


def share_bar(cfg, t, card_url):
    page_url = f"{cfg.public_url}/t/{t['id']}"
    text = "Uncle Vern, 78, is writing back to a scammer. Read along:"
    x = "https://x.com/intent/tweet?" + urllib.parse.urlencode({"text": text, "url": page_url})
    card = f' · <a href="{esc(card_url)}" download="uncle-vern-{t["id"]}.png">Save the card</a>' if card_url else ""
    return (f'<p class="share">Share this one: <a href="{esc(x)}" target="_blank" rel="noopener">Post on X</a>'
            f' · <a href="{esc(page_url)}" class="copy">Copy the link</a>{card}</p>'
            '<script>document.querySelectorAll(".copy").forEach(function(a){a.addEventListener("click",function(e){'
            'if(!navigator.clipboard)return;e.preventDefault();navigator.clipboard.writeText(a.href).then(function(){'
            'a.textContent="Link copied";});});});</script>')


def by_mail(cfg):
    if not cfg.inbox:
        return ""
    return (f'<p class="bymail"><b>Or try him by email.</b> Forward a scam from your own inbox to '
            f'<a href="mailto:{esc(cfg.inbox)}">{esc(cfg.inbox)}</a>. The email wakes him up, and he mails you '
            "the letter he'd send, usually within a minute. Nothing goes to the scammer unless his boss reads "
            "it and says yes.</p>")


def desk(latest_scam, letters_out=0):
    """Hero still life: the newest real scammer letter under Uncle's sticky note."""
    if latest_scam:
        sheet = (f'<div class="paper office sheet"><div class="head"><span>{esc(latest_scam.get("label") or "Received")}</span><span>{esc(ago(latest_scam["sent_at"]))}</span></div>'
                 f'<div class="body">{letter_body(latest_scam["public_body"][:520])}</div></div>')
    else:
        waiting = (f"{letters_out} {'letter is' if letters_out == 1 else 'letters are'} in the mail. I check "
                   "the box after my oatmeal." if letters_out else "My first letters go out soon.")
        sheet = ('<div class="paper office sheet"><div class="head"><span>Uncle\'s in-tray</span><span>empty</span></div>'
                 f'<div class="body">No scammer has written back yet.\n\n{esc(waiting)}</div></div>')
    return f"""<div class="desk"><div class="paper office sheet under"></div>{sheet}
<div class="sticky">Send me your scams. I've got all the time in the world.<small>Uncle V.</small></div></div>"""


def home(cfg, totals, meter, threads, letters_by_thread, diary, keys_on_box, latest_scam=None, wakes=(),
         card=None):
    cards = "".join(thread_card(t, letters_by_thread.get(t["id"], [])) for t in threads) or \
        '<div class="empty">No pen pals yet. Uncle is sitting by the mailbox.</div>'
    diary_html = "".join(
        f'<li><time>{esc(ago(d["at"]))}</time><span>{esc(d["text"])}</span></li>' for d in diary) or \
        '<li><time></time><span>Nothing yet.</span></li>'
    hook = dur(totals["longest_hook_s"]) if totals["longest_hook_s"] else "-"
    wasted = wasted_seconds(totals)
    body = f"""{header(meter)}
<section class="hero"><div>
<h1>Uncle Vern answers scam emails. <em>All of them.</em> <em>At length.</em></h1>
<p class="lede">Forward him a scam and he writes back to the scammer, about his Buick, his ferret Doug and which
Western Union is nearest the Piggly Wiggly. <b>Every hour a scammer spends on Uncle is an hour they don't spend
on someone's grandma.</b></p>
<div class="ctas"><a class="btn" href="#try">Try him on a scam</a><a class="btn ghost" href="#mailbag">Read the mailbag</a></div>
</div>{desk(latest_scam, sum(1 for t in threads if t['status'] == 'active'))}</section>

<div class="ledger">
{wasted_tile(wasted, totals)}
<div><b>{odo(totals['approached'])}</b><small>Scammers written to</small></div>
<div><b>{odo(totals['bit'])}</b><small>Wrote back</small></div>
<div><b>{odo(totals['uncle_letters'])}</b><small>Letters from Uncle</small></div>
<div><b>{odo(totals['scammer_letters'])}</b><small>Letters from scammers</small></div>
<div><b>{odo(totals['scammer_words'])}</b><small>Words scammers typed</small></div>
<div><b>{esc(hook)}</b><small>Longest on the hook</small></div>
</div>
<p class="foot-note">Uncle has been awake {esc(dur(meter.get('awake_s', 0)))} in total, over {num(meter.get('wakes'))}
wake-ups. The rest of the time he's asleep on a Fly.io Sprite, and the next letter wakes him. Time wasted is an
estimate: his
letters in conversations where the scammer wrote back, read at {READ_WPM} words a minute, plus every word they
typed, at {WRITE_WPM} a minute.</p>
{wake_strip(wakes, time.time())}

<h2 id="try">Try him <small>practice only: nothing is sent to anyone</small></h2>
<div class="try">
<form id="tryform"><textarea name="text" aria-label="A scam email" required
placeholder="Paste a scam email here.&#10;&#10;Dear Beloved, I am Barrister ... you have been selected as next of kin to receive the sum of ..."></textarea>
<p><button class="btn" type="submit">Ask Uncle to write back</button>
<button class="btn ghost" type="button" id="sample">Use a sample scam</button></p></form>
<div class="out" id="out"><div class="wait">Uncle's letter will appear here.</div></div>
</div>
{by_mail(cfg)}

<h2 id="mailbag">The mailbag <small>scammers' addresses, numbers, links and names are blacked out</small></h2>
<div class="bag">{cards}</div>

<h2>How it works</h2>
<div class="steps">
<div class="card"><b>ONE</b><h4>You forward him a scam</h4><p>Hit Forward on any scam in your spam folder and send
it to Uncle's own inbox. {dn()} ({dabout()}) checks it really is a scam and finds the address the
scammer wants a reply at.</p></div>
<div class="card"><b>TWO</b><h4>You say yes</h4><p>Uncle emails you his first letter. Reply "yes" in your own
words and it goes out. {dn()} reads your reply, so "go get 'em" works too.</p></div>
<div class="card"><b>THREE</b><h4>He sleeps, then wakes</h4><p>Uncle lives on one Fly.io Sprite. When the scammer
writes back, the email webhook wakes him. {dn()} reads how hooked and how cross they are, {vn()} writes his reply,
and a checker stops any number, link or address going out.</p></div>
</div>
<div class="rules">House rules: I only write to scammers you send me, and you OK my first letter. I never send
money, links or real details. And I stop the minute anybody asks. <span style="float:right">V.</span></div>

<h2>Uncle's diary</h2>
<ul class="diary">{diary_html}</ul>

{SCENE}
<footer>Runs on one Fly.io Sprite. Connectors: AgentMail (his inbox), {connectors_line()}.
API keys stored on this machine: <b>{keys_on_box}</b>, so there's nothing for a
scammer to talk him out of.<br>
Credit where it's due: Netsafe's Re:scam (New Zealand, 2017) and O2's Daisy (UK, 2024) wasted scammers' time for a
whole country. Uncle Vern is your own. · <a href="{esc(cfg.code_url)}">Code</a></footer>
<script>{TRY_JS}</script>"""
    return page("Uncle Vern answers scam emails", body, image=card, url=cfg.public_url + "/")


def original_scam(t):
    """The scam the boss forwarded, redacted like every scammer letter."""
    return redact.redact(t.get("scam_text") or "", names=[t["scammer_name"]] if t.get("scammer_name") else [])


def thread_page(cfg, meter, t, letters, diary, card=None):
    parts = []
    if t.get("scam_text") and not (letters and letters[0]["direction"] == "scammer"):
        stamp = f'<div class="stampmark">{postmark(round((t["scam_prob"] or 0) * 100), "SCAM", dn().upper(), 70)}</div>'
        parts.append(f'<div class="s"><p class="from">The scam that started it · forwarded by the boss</p>'
                     f'<div class="paper office">{stamp}<div class="head"><span>Received · redacted copy</span></div>'
                     f'<div class="body">{letter_body(original_scam(t)[:3000])}</div></div></div>')
    for l in letters:
        if l["direction"] == "uncle":
            parts.append(f'<div class="u"><p class="from">Uncle Vern wrote · {esc(ago(l["sent_at"]))}</p>'
                         f'<div class="paper notepad"><div class="body">{letter_body(l["public_body"])}</div></div></div>')
        else:
            j = jev_of(l)
            stamp = ""
            jl = ""
            if j:
                ask = WANTS.get(j.get("asking_for"), "do something")
                stamp = f'<div class="stampmark">{postmark(round(j.get("still_hooked", 0) * 100), "HOOKED", dn().upper(), 70)}</div>'
                jl = (f'<p class="meta" style="margin-top:8px">{dn()} on this letter: {round(j.get("is_scam", 0) * 100)}% '
                      f'still a scam, {round(j.get("still_hooked", 0) * 100)}% still hooked, mood '
                      f'{float(j.get("frustration", 0)):.1f} of 4, wants Uncle to {esc(ask)}.</p>')
            parts.append(f'<div class="s"><p class="from">The scammer wrote · {esc(ago(l["sent_at"]))}</p>'
                         f'<div class="paper office">{stamp}<div class="head"><span>Received · redacted copy</span></div>'
                         f'<div class="body">{letter_body(l["public_body"])}</div></div>{jl}</div>')
    if t["status"] == "active" and letters and letters[-1]["direction"] == "uncle":
        parts.append('<p class="asleep">Uncle is asleep now. Their reply will wake him.</p>')
    diary_html = "".join(f'<li><time>{esc(ago(d["at"]))}</time><span>{esc(d["text"])}</span></li>' for d in diary)
    status = {"active": "on the hook", "closed": f"closed: {t['close_reason'] or ''}"}.get(t["status"], t["status"])
    body = f"""{header(meter)}
<div class="thread-head"><div class="tag" style="margin:0">{esc(SCAM_LABEL.get(t['scam_type'], 'Scam'))} ·
{dn()} {round((t['scam_prob'] or 0) * 100)}% scam · {esc(status)}</div>
<h1>{esc(redact.subject(t['scam_subject']) or 'A letter')}</h1>
<p class="meta">The subject line, as the scammer wrote it.</p>
{frustration_meter(t['frustration']) if t['first_bite_at'] else ''}{share_bar(cfg, t, card)}</div>
<div class="conv">{''.join(parts)}</div>
<h2>Uncle's diary for this one</h2><ul class="diary">{diary_html}</ul>
{SCENE}
<footer><a href="/">Back to the mailbag</a> · Scammers' letters have addresses, numbers, links and names blacked out.</footer>"""
    n = sum(1 for l in letters if l["direction"] == "uncle")
    desc = (f"Uncle Vern, 78, is writing back to a scammer ({SCAM_LABEL.get(t['scam_type'], 'scam').lower()}). "
            f"{n} letter{'' if n == 1 else 's'} from Uncle so far.")
    return page(f"Uncle Vern vs. {redact.subject(t['scam_subject']) or 'a scammer'}", body, desc,
                image=card, url=f"{cfg.public_url}/t/{t['id']}")


# Rolling odometer digits, like the Buick's. Falls back to plain numbers without JS.
ODO_JS = r"""
(function(){
  var reduce = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  document.querySelectorAll('.odo-num').forEach(function(el){
    var txt = el.textContent; if (reduce) return;
    var wrap = document.createElement('span'); wrap.className = 'odo';
    var cols = [];
    for (var i = 0; i < txt.length; i++){
      var ch = txt[i];
      if (ch < '0' || ch > '9'){ var s = document.createElement('span'); s.className='sep'; s.textContent = ch; wrap.appendChild(s); continue; }
      var col = document.createElement('span'); col.className = 'col';
      for (var d = 0; d <= 9; d++){ var c = document.createElement('span'); c.textContent = d; col.appendChild(c); }
      col.style.transitionDelay = (i * 90) + 'ms';
      wrap.appendChild(col); cols.push([col, +ch]);
    }
    el.textContent = ''; el.appendChild(wrap);
    requestAnimationFrame(function(){ requestAnimationFrame(function(){
      cols.forEach(function(p){ p[0].style.transform = 'translateY(' + (-p[1] * 1.1) + 'em)'; });
    }); });
  });
})();
"""

# Uncle types his practice letter himself, hunt-and-peck, with the odd typo he goes back to fix.
TRY_JS = r"""
(function(){
  var f = document.getElementById('tryform'), out = document.getElementById('out');
  var SAMPLE = "Subject: URGENT: Unclaimed Inheritance Fund\n\nDear Beloved,\n\nI am Barrister James Okoro, " +
    "personal attorney to the late Mr. Henry, who died with his family in a car accident. You have been " +
    "identified as his next of kin to receive the sum of USD 4,500,000 in his estate.\n\nKindly reply with " +
    "your full name, phone number and bank details so the processing fee of USD 250 can be arranged and " +
    "the funds released to you. This is urgent and confidential.\n\nRegards,\nBarrister James Okoro";
  document.getElementById('sample').addEventListener('click', function(){ f.text.value = SAMPLE; f.text.focus(); });
  function esc(s){ return String(s).replace(/[&<>"]/g, function(c){ return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }
  var reduce = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  var near = 'qwertyuiopasdfghjklzxcvbnm';
  // Hunt-and-peck, with the odd typo he goes back to fix, but done in about eight seconds.
  function type(el, text, done){
    if (reduce){ el.textContent = text; return done && done(); }
    var i = 0, buf = '', skip = false, k = Math.max(1, Math.round(text.length / 450));
    el.classList.add('typing');
    el.title = 'Click to let Uncle finish';
    el.parentNode.addEventListener('click', function(){ skip = true; }, {once: true});
    (function step(){
      if (skip){ i = text.length; buf = text; el.textContent = text; }
      if (i >= text.length){ el.classList.remove('typing'); el.title = ''; return done && done(); }
      var ch = text[i];
      if (/[a-z]/.test(ch) && Math.random() < 0.012){
        var wrong = near[(near.indexOf(ch) + 1) % near.length];
        el.textContent = buf + wrong;
        return setTimeout(function(){ el.textContent = buf; setTimeout(step, 60); }, 140);
      }
      var piece = text.slice(i, i + k); buf += piece; i += piece.length; el.textContent = buf;
      var pause = /[.!?]/.test(piece) ? 70 : /\n/.test(piece) ? 40 : 8 + Math.random() * 8;
      setTimeout(step, pause);
    })();
  }
  var convo = null, n = 0;
  function uncleLetter(box, j, after){
    var id = 'typed' + (++n);
    box.insertAdjacentHTML('beforeend', '<p class="from" style="margin-top:18px">Uncle Vern wrote <span class="meta">(click to let him finish)</span></p>' +
      '<div class="paper notepad"><div class="body" id="' + id + '"></div></div>');
    type(document.getElementById(id), j.letter, after);
  }
  function replyBox(box){
    if (!convo || convo.turns.length >= 7){
      box.insertAdjacentHTML('beforeend', '<p class="read">That\'s as far as practice goes. A real scammer gets to keep going.</p>');
      return;
    }
    box.insertAdjacentHTML('beforeend', '<div class="replybox"><p class="meta"><b>Now you be the scammer.</b> ' +
      'Write back as them (push him, get cross, ask for the fee) and see how Uncle answers.</p>' +
      '<textarea aria-label="Your reply as the scammer" placeholder="Dear Vern, you must send the fee TODAY by Western Union..."></textarea>' +
      '<p><button class="btn" type="button">Send as the scammer</button></p></div>');
    var rb = box.lastElementChild, ta = rb.querySelector('textarea'), btn = rb.querySelector('button');
    btn.addEventListener('click', function(){
      var reply = ta.value.trim();
      if (reply.length < 5){ ta.focus(); return; }
      btn.disabled = true; btn.textContent = 'Uncle is reading it...';
      fetch('/api/try/reply', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({scam: convo.scam, turns: convo.turns, reply: reply})})
        .then(function(r){ return r.json(); })
        .then(function(j){
          if (j.error){ btn.disabled = false; btn.textContent = 'Send as the scammer'; rb.insertAdjacentHTML('beforeend', '<p class="read">' + esc(j.error) + '</p>'); return; }
          rb.outerHTML = '<p class="from" style="margin-top:18px">You, as the scammer</p><div class="paper office"><div class="body">' + esc(reply) + '</div></div>' +
            '<p class="read">' + esc(j.read) + '</p>';
          convo.turns.push({who: 'scammer', text: reply});
          if (!j.letter){ box.insertAdjacentHTML('beforeend', '<p class="read">' + esc(j.note) + '</p>'); return; }
          convo.turns.push({who: 'uncle', text: j.letter});
          uncleLetter(box, j, function(){ replyBox(box); });
        })
        .catch(function(){ btn.disabled = false; btn.textContent = 'Send as the scammer'; });
    });
  }
  f.addEventListener('submit', function(e){
    e.preventDefault();
    var b = f.querySelector('button[type=submit]'); b.disabled = true; b.textContent = 'Uncle is finding his glasses...';
    out.innerHTML = '<div class="wait">Uncle is reading it slowly, with his finger.</div>';
    var scam = f.text.value;
    fetch('/api/try', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({text: scam})})
      .then(function(r){ return r.json(); })
      .then(function(j){
        if (j.error){ out.innerHTML = '<div class="wait">' + esc(j.error) + '</div>'; return; }
        var pct = Math.round(j.scam_prob * 100), kind = esc(String(j.scam_type).replace(/_/g, ' '));
        var h = '<p class="meta">' + esc(j.decider || 'Jev') + ' says ' + pct + '% scam (' + kind + ').</p>';
        if (!j.letter){ out.innerHTML = h + '<div class="wait">' + esc(j.note) + '</div>'; return; }
        out.innerHTML = h;
        convo = {scam: scam, turns: [{who: 'uncle', text: j.letter}]};
        uncleLetter(out, j, function(){ out.insertAdjacentHTML('beforeend', '<p class="meta">' + esc(j.note) + '</p>'); replyBox(out); });
      })
      .catch(function(){ out.innerHTML = '<div class="wait">Uncle dropped the phone. Try again.</div>'; })
      .then(function(){ b.disabled = false; b.textContent = 'Ask Uncle to write back'; });
  });
})();
"""
