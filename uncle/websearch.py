"""Has anyone already posted this exact scam online? Apify's Google Search Scraper, through the Sprites connector.

Uncle searches the web for one distinctive sentence from a scam, in quotes. People who get scams post them on
warning sites, so a long sentence found word for word on other pages is the same letter going round.

Measured Nov 27: a NESREA sentence turned up on five pages posted that month (two Scambuster pages, kometa.cl,
niepodam.pl, an RSS mirror); a fresh LinkedIn romance opener had no copies. Searching the scammer's address finds
nothing useful: fresh addresses aren't on the web, and Google pads the results with Gmail help pages.

The connector allows starting a run, polling it and reading its dataset (not the one-call run-sync endpoint).
Without an Apify connector Uncle simply doesn't look; nothing else changes.
"""
import json
import re
import threading
import time
import urllib.parse

from . import gateway, net, redact

ACTOR = "apify~google-search-scraper"
RUN = 6  # words in a row that must match for a page to count as a copy


def words(text):
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def copies(phrase, results):
    """The pages (one per site) whose snippet repeats at least RUN words of the phrase in a row."""
    p = words(phrase)
    grams = {" ".join(p[i:i + RUN]) for i in range(max(0, len(p) - RUN + 1))}
    out, sites = [], set()
    for r in results or []:
        snippet = " ".join(words(f"{r.get('title', '')} {r.get('description', '')}"))
        site = urllib.parse.urlparse(r.get("url") or "").netloc.lower().removeprefix("www.")
        if site and site not in sites and any(f" {g} " in f" {snippet} " for g in grams):
            sites.add(site)
            out.append({"site": site, "title": (r.get("title") or "")[:100], "url": r.get("url")})
    return out


def safe(sentence):
    """Only a sentence the page would show unredacted goes out to the web: no addresses, links, numbers,
    names after a title, 'Dear <name>' greetings or the boss's own words."""
    s = (sentence or "").strip()
    return bool(s) and redact.BLOCK_CHAR not in s and redact.redact(s) == s


def good_quote(quote, text):
    """The sentence to search for: Claude's pick if it really is in the email, else the email's first long
    sentence. Never one with anybody's details in it."""
    flat = f" {' '.join(words(text))} "
    q = " ".join((quote or "").split())
    if len(words(q)) >= 7 and f" {' '.join(words(q))} " in flat and safe(q):
        return q
    for s in re.split(r"(?<=[.!?])\s+", " ".join((text or "").split())):
        ws = s.split()
        if len(ws) >= 10:
            cut = " ".join(ws[:14])
            if safe(cut):
                return cut
    return None


class ApifySearch:
    name = "Apify"

    def __init__(self):
        self._ep = None
        self._missing_until = 0.0
        self._lock = threading.Lock()

    def available(self):
        with self._lock:
            if self._ep:
                return True
            if time.time() < self._missing_until:
                return False
            try:
                self._ep = gateway.resolve("apify")
                return True
            except Exception:  # noqa: BLE001  (no connector yet: ask the gateway again in ten minutes)
                self._missing_until = time.time() + 600
                return False

    def search(self, query, wait=90):
        """Google's first page of results for an exact phrase: [{url, title, description}]."""
        if not self.available():
            return []
        body = {"queries": f'"{query}"', "maxPagesPerQuery": 1, "resultsPerPage": 10, "mobileResults": False,
                "saveHtml": False, "saveHtmlToKeyValueStore": False, "includeUnfilteredResults": False}
        h = self._ep.headers
        run = net.request("POST", self._ep.url(f"/v2/actors/{ACTOR}/runs"), body, headers=h, timeout=60)["data"]
        deadline = time.time() + wait
        while run.get("status") in ("READY", "RUNNING"):
            if time.time() > deadline:
                raise TimeoutError("Apify search still running")
            time.sleep(3)
            run = net.request("GET", self._ep.url(f"/v2/actor-runs/{run['id']}"), headers=h, timeout=30)["data"]
        if run.get("status") != "SUCCEEDED":
            raise RuntimeError(f"Apify run {run.get('status')}")
        items = net.request("GET", self._ep.url(f"/v2/datasets/{run['defaultDatasetId']}/items?clean=true"),
                            headers=h, timeout=30)
        return [r for it in (items if isinstance(items, list) else []) for r in it.get("organicResults") or []]


class MockSearch:
    """For tests and local runs: every phrase has been posted on one warning site."""
    name = "Apify"

    def __init__(self):
        self.queries = []

    def available(self):
        return True

    def search(self, query, wait=90):
        self.queries.append(query)
        return [{"url": "https://scam-warnings.example/2026/11/a", "title": "Another 419 scam",
                 "description": f"... {query} ..."},
                {"url": "https://support.mail.example/help", "title": "Help", "description": "Sign in to your mail."}]


class WebCheck:
    """One search per sentence (remembered a week), at most `per_day` searches a day."""

    def __init__(self, store, searcher, per_day=40):
        self.store = store
        self.searcher = searcher
        self.per_day = per_day

    @property
    def name(self):
        return self.searcher.name

    def available(self):
        return self.searcher.available()

    def cached(self, phrase):
        """This week's search for this sentence, if Uncle already did one."""
        hit = self.store.one("SELECT result FROM web_checks WHERE phrase=? AND at>=? ORDER BY at DESC",
                             (phrase, time.time() - 7 * 86400)) if phrase else None
        return json.loads(hit["result"]) if hit else None

    def check(self, phrase, wait=90):
        """{"phrase", "found": [{site, title, url}], "at"}, or None when Uncle can't look right now."""
        if not phrase or not self.available():
            return None
        now = time.time()
        hit = self.cached(phrase)
        if hit:
            return hit
        if self.store.one("SELECT COUNT(*) n FROM web_checks WHERE at>=?", (now - 86400,))["n"] >= self.per_day:
            return None
        result = {"phrase": phrase, "found": copies(phrase, self.searcher.search(phrase, wait=wait)), "at": now}
        self.store.run("INSERT INTO web_checks(phrase, at, result) VALUES(?,?,?)", (phrase, now, json.dumps(result)))
        return result


def web_line(result, name="Apify"):
    """What Uncle says about it, in plain words. '' when he didn't look, or the search isn't back yet."""
    if not result or "at" not in result:
        return ""
    found = result.get("found") or []
    if not found:
        return (f"I had {name} search the web for a sentence from this letter and found no copies yet, so it "
                "may be a fresh one.")
    sites = [f["site"] for f in found[:3]]
    named = sites[0] if len(sites) == 1 else ", ".join(sites[:-1]) + " and " + sites[-1]
    n = len(found)
    return (f"This letter is already going round: {name} found the same words on {n} other "
            f"{'page' if n == 1 else 'pages'} where people post the scams they get, like {named}.")
