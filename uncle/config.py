"""Settings, read from the environment. Nothing here is a secret."""
import os


def _list(value):
    return [v.strip().lower() for v in (value or "").split(",") if v.strip()]


class Config:
    def __init__(self, **overrides):
        e = os.environ.get
        self.db_path = e("UNCLE_DB", os.path.join(os.getcwd(), "data", "uncle.db"))
        self.port = int(e("PORT", "8080"))
        self.public_url = e("PUBLIC_URL", "http://localhost:8080").rstrip("/")
        self.code_url = e("CODE_URL", "https://github.com/")
        # The people allowed to point Uncle at a scammer and approve his letters.
        self.owner_emails = _list(e("OWNER_EMAILS", ""))
        # Uncle's own AgentMail inbox, e.g. uncle.vern@agentmail.to
        self.inbox = e("UNCLE_INBOX", "").strip().lower()
        # Uncle's voice on Ollama. A comma list: the first model this account can use wins.
        self.model = e("UNCLE_MODEL", "gpt-oss:120b,gpt-oss:20b")
        # Who makes the decisions: "typesafe" (Jev), "anthropic" (Claude), "ollama" (Clef), or "auto":
        # the first of those whose connector this Sprite has.
        self.decider = e("UNCLE_DECIDER", "auto").strip().lower()
        # Who writes the letters: "ollama", "anthropic", or "auto" (Claude if that connector is here).
        self.writer = e("UNCLE_WRITER", "auto").strip().lower()
        self.decider_model = e("UNCLE_DECIDER_MODEL", "") or None
        self.think = e("UNCLE_THINK", "low")  # gpt-oss takes low/medium/high; others take true/false
        self.mock = e("UNCLE_MOCK", "") == "1"
        # Guard rails
        self.scam_threshold = float(e("SCAM_THRESHOLD", "0.75"))
        self.stranger_threshold = float(e("STRANGER_THRESHOLD", "0.92"))
        self.max_active_threads = int(e("MAX_ACTIVE_THREADS", "20"))
        self.max_letters_per_thread_day = int(e("MAX_LETTERS_PER_THREAD_DAY", "6"))
        self.max_letters_day = int(e("MAX_LETTERS_DAY", "80"))
        self.try_per_ip_hour = int(e("TRY_PER_IP_HOUR", "6"))
        self.try_per_day = int(e("TRY_PER_DAY", "300"))
        for k, v in overrides.items():
            setattr(self, k, v)
