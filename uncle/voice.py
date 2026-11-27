"""Uncle reads his letters aloud: Deepgram's Aura-2 text-to-speech, through the Sprites connector.

Each letter is recorded once and kept on the Sprite's disk, so a letter costs one call however many people
press play, and at most `per_day` new recordings are made a day. Without a Deepgram connector the page
falls back to the browser's own voice, and nothing else changes.
"""
import hashlib
import os
import re
import threading
import time

from . import gateway, net

# Pluto: smooth, calm, a baritone. Picked by ear over Atlas, Deepgram's one "mature" American man.
MODEL = "aura-2-pluto-en"
MAX_CHARS = 1900  # Deepgram takes up to 2,000 characters a request
DAY = 86400


def speakable(text):
    """What gets read out: blacked-out bits dropped, tidy spacing, cut at a sentence if it's too long."""
    text = re.sub("█+", "", text or "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    if len(text) > MAX_CHARS:
        cut = text[:MAX_CHARS]
        end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "), cut.rfind("\n"))
        text = cut[:end + 1] if end > MAX_CHARS // 2 else cut
    return text.strip()


class Deepgram:
    name = "Deepgram"

    def __init__(self, model=MODEL):
        self.model = model
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
                self._ep = gateway.resolve("deepgram")
                return True
            except Exception:  # noqa: BLE001
                self._missing_until = time.time() + 600  # ask the gateway again in ten minutes
                return False

    def synth(self, text):
        if not self.available():
            raise RuntimeError("no Deepgram connector")
        audio = net.request("POST", self._ep.url(f"/v1/speak?model={self.model}&encoding=mp3"), {"text": text},
                            headers={**self._ep.headers, "Accept": "audio/mpeg"}, timeout=40, retries=1)
        if not isinstance(audio, (bytes, bytearray)) or len(audio) < 500:
            raise RuntimeError("Deepgram sent back no audio")
        return bytes(audio)


class MockSpeaker:
    """For tests and local runs: a few bytes that start like an MP3."""
    name = "Mock voice"
    model = "mock"

    def __init__(self):
        self.calls = 0

    def available(self):
        return True

    def synth(self, text):
        self.calls += 1
        return b"ID3" + hashlib.sha256(text.encode()).digest() * 20


class Voice:
    def __init__(self, folder, speaker, per_day=150):
        self.folder = folder
        self.speaker = speaker
        self.per_day = per_day
        self._lock = threading.Lock()
        self._tries = {}  # key -> text: the try box's recent letters, in memory only

    @property
    def name(self):
        return self.speaker.name

    def available(self):
        return self.speaker.available()

    def key(self, text):
        return hashlib.sha256(f"{self.speaker.model}\n{speakable(text)}".encode()).hexdigest()[:32]

    def remember_try(self, text):
        """A practice letter someone may want to hear. Only letters Uncle wrote get a voice, never any text."""
        k = self.key(text)
        with self._lock:
            self._tries[k] = text
            while len(self._tries) > 500:
                self._tries.pop(next(iter(self._tries)))
        return k

    def try_text(self, key):
        return self._tries.get(key)

    def _made_today(self):
        try:
            now = time.time()
            return sum(1 for f in os.scandir(self.folder) if f.name.endswith(".mp3") and f.stat().st_mtime > now - DAY)
        except FileNotFoundError:
            return 0

    def audio(self, text):
        """MP3 bytes for a letter, from the disk if it's been read before. None if over today's limit."""
        text = speakable(text)
        if not text:
            return None
        path = os.path.join(self.folder, self.key(text) + ".mp3")
        if os.path.exists(path):
            with open(path, "rb") as f:
                return f.read()
        with self._lock:
            if self._made_today() >= self.per_day:
                return None
        data = self.speaker.synth(text)
        os.makedirs(self.folder, exist_ok=True)
        tmp = f"{path}.{threading.get_ident()}.tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
        return data
