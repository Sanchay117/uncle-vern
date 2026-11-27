"""Where each outside service lives.

On a Sprite, every call goes through Fly's connector gateway, which adds the
credential on the way out. Uncle never sees a key. Off a Sprite (local dev),
a key in the environment sends calls straight to the service instead.
"""
import json
import os
import threading

from . import net

GATEWAY_LIST = os.environ.get("SPRITES_GATEWAY_LIST", "https://api.sprites.dev/v1/gateway/list")

SERVICES = {
    # name: (hints to match in the gateway list, direct base url, env var with a key)
    "agentmail": (["agentmail"], "https://api.agentmail.to", "AGENTMAIL_API_KEY"),
    "jev": (["typesafe", "systemone", "jev"], "https://api.typesafe.ai", "TYPESAFE_API_KEY"),
    "ollama": (["ollama"], "https://ollama.com", "OLLAMA_API_KEY"),
    "anthropic": (["anthropic"], "https://api.anthropic.com", "ANTHROPIC_API_KEY"),
    "pinecone": (["pinecone"], "https://api.pinecone.io", "PINECONE_API_KEY"),
}

# Services that take their key in a header of their own rather than "Authorization: Bearer".
KEY_HEADER = {"pinecone": "Api-Key"}


def _auth(name, key):
    if not key:
        return {}
    h = KEY_HEADER.get(name)
    return {h: key} if h else {"Authorization": f"Bearer {key}"}

KEY_VARS = [v[2] for v in SERVICES.values()]


class Endpoint:
    def __init__(self, base, headers=None, via="gateway"):
        self.base = base.rstrip("/")
        self.headers = headers or {}
        self.via = via

    def url(self, path):
        return self.base + "/" + path.lstrip("/")

    def __repr__(self):
        return f"Endpoint({self.base!r}, via={self.via})"


_lock = threading.Lock()
_cache = {}


def _walk(node):
    """Yield every dict in a JSON tree."""
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def _base_from_entry(entry):
    for key in ("gateway_base_url", "base_url", "gateway_url", "url"):
        v = entry.get(key)
        if isinstance(v, str) and v.startswith("http") and "/gateway/" in v:
            return v
    return None


def parse_gateway_list(doc, hints):
    """Find the gateway base URL for the first connector whose entry mentions a hint."""
    for entry in _walk(doc):
        base = _base_from_entry(entry)
        if not base:
            continue
        blob = json.dumps(entry).lower()
        if any(h in blob for h in hints):
            return base
    return None


def keys_on_box():
    """How many service keys this process can see. On the Sprite this should be 0."""
    return sum(1 for v in KEY_VARS if os.environ.get(v))


def resolve(name):
    hints, direct, key_var = SERVICES[name]
    override = os.environ.get(f"{name.upper()}_BASE")
    key = os.environ.get(key_var)
    if override:
        return Endpoint(override, _auth(name, key), via="override")
    if key:
        return Endpoint(direct, _auth(name, key), via="direct")
    with _lock:
        if name in _cache:
            return _cache[name]
        doc = net.request("GET", GATEWAY_LIST, timeout=20)
        base = parse_gateway_list(doc, hints)
        if not base:
            raise RuntimeError(
                f"No Sprites connector found for {name}. Add it in the Fly dashboard "
                f"and give this Sprite access (gateway list: {GATEWAY_LIST})."
            )
        ep = Endpoint(base, via="gateway")
        _cache[name] = ep
        return ep


def describe():
    """For the status page: how each service is reached."""
    out = {}
    for name in SERVICES:
        try:
            out[name] = resolve(name).via
        except Exception as exc:  # noqa: BLE001
            out[name] = f"missing ({exc.__class__.__name__})"
    return out
