"""Claude, through the Sprites Anthropic connector.

It can stand in for either half of Uncle's brain:
  - his voice: `chat(messages)` has the same shape as clients.Ollama.chat
  - his judgement: `ask(state, questions)` takes Jev's questions (noul, choice, score)
    and answers in Jev's shape, using structured outputs so the JSON always parses.

On a Sprite the gateway swaps in the real key, so the SDK gets a placeholder.
"""
import json
import os

from . import gateway

FALLBACK_BETA = "server-side-fallback-2026-07-01"

JUDGE_SYSTEM = (
    "You make careful judgement calls for an email assistant that answers scammers. "
    "Read the state and answer every question. Give calibrated numbers: a yes/no probability of 0.5 means "
    "you can't tell, 0.95 means you are nearly sure. Confidence is how sure you are of your pick, 0 to 1."
)


class Refused(RuntimeError):
    pass


def _schema(questions):
    props = {}
    for key, q in questions.items():
        if q["type"] == "noul":
            fields = {"p_yes": {"type": "number", "description": "Probability from 0 to 1 that the answer is yes"}}
        elif q["type"] == "choice":
            fields = {"choice": {"type": "string", "enum": list(q["criteria"])},
                      "confidence": {"type": "number", "description": "0 to 1"}}
        elif q["type"] == "score":
            fields = {"level": {"type": "integer", "description": f"0 to {len(q['criteria']) - 1}"},
                      "confidence": {"type": "number", "description": "0 to 1"}}
        elif q["type"] == "list":
            fields = {"items": {"type": "array", "items": {"type": "string"},
                                "description": f"At most {q.get('most', 4)} items"}}
        else:
            continue
        props[key] = {"type": "object", "properties": fields, "required": list(fields), "additionalProperties": False}
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def _question_text(questions):
    lines = []
    for key, q in questions.items():
        if q["type"] == "noul":
            lines.append(f"- {key} (yes/no): {q['instructions']}")
        elif q["type"] == "choice":
            opts = "; ".join(f"{name}: {desc}" for name, desc in q["criteria"].items())
            lines.append(f"- {key} (pick one): {q['instructions']} Options: {opts}")
        elif q["type"] == "score":
            levels = "; ".join(f"{i}: {desc}" for i, desc in enumerate(q["criteria"]))
            lines.append(f"- {key} (pick a level): {q['instructions']} Levels: {levels}")
        elif q["type"] == "list":
            lines.append(f"- {key} (a list, at most {q.get('most', 4)} items): {q['instructions']}")
    return "\n".join(lines)


def _clamp(x, lo=0.0, hi=1.0):
    try:
        return max(lo, min(hi, float(x)))
    except (TypeError, ValueError):
        return lo


def to_jev(questions, raw):
    """Turn Claude's JSON into the answer shape Jev returns, so the engine can't tell them apart."""
    out = {}
    for key, q in questions.items():
        a = raw.get(key) or {}
        if q["type"] == "noul":
            out[key] = {"type": "noul", "noul": _clamp(a.get("p_yes"))}
        elif q["type"] == "choice":
            names = list(q["criteria"])
            pick = a.get("choice") if a.get("choice") in names else names[-1]
            out[key] = {"type": "choice", "choice": pick, "confidence": _clamp(a.get("confidence"))}
        elif q["type"] == "score":
            n = len(q["criteria"])
            out[key] = {"type": "score", "score": _clamp(a.get("level"), 0, n - 1),
                        "confidence": _clamp(a.get("confidence"))}
        elif q["type"] == "list":
            items = [str(x).strip()[:200] for x in (a.get("items") or []) if str(x).strip()]
            out[key] = {"type": "list", "items": items[:q.get("most", 4)]}
    return out


class Claude:
    name, maker, about = "Claude", "Anthropic", "Anthropic's model"
    provider = "anthropic"
    lists = True  # can answer "list" questions (red flags), which Jev's API has no shape for

    def __init__(self, client=None, model=None, effort=None):
        self._client = client
        self.model = model or os.environ.get("UNCLE_CLAUDE_MODEL", "claude-opus-5-5")
        self.effort = effort or os.environ.get("UNCLE_CLAUDE_EFFORT", "low")

    @property
    def client(self):
        if self._client is None:
            import anthropic  # only needed on the Sprite; tests pass a fake client

            ep = gateway.resolve("anthropic")
            if ep.via == "gateway":
                # The connector replaces whatever key the SDK sends.
                self._client = anthropic.Anthropic(base_url=ep.base, api_key="via-sprites-gateway", timeout=120.0)
            else:
                self._client = anthropic.Anthropic(base_url=ep.base, timeout=120.0)
        return self._client

    def _create(self, system, messages, max_tokens, output_format=None):
        output_config = {"effort": self.effort}
        if output_format:
            output_config["format"] = output_format
        resp = self.client.beta.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
            output_config=output_config,
            betas=[FALLBACK_BETA],
            fallbacks="default",  # on a safety decline, the API reruns the request on a fallback model
        )
        if resp.stop_reason == "refusal":
            details = getattr(resp, "stop_details", None)
            raise Refused(f"Claude declined ({getattr(details, 'category', None)})")
        return next((b.text for b in resp.content if b.type == "text"), "")

    # -- Uncle's voice (same call shape as clients.Ollama.chat)
    def chat(self, messages, temperature=0.9, max_tokens=900):
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        convo = [{"role": m["role"], "content": m["content"]} for m in messages if m["role"] != "system"]
        if not convo or convo[0]["role"] != "user":
            convo.insert(0, {"role": "user", "content": "(Your letters with this person so far.)"})
        # Thinking counts toward max_tokens, so leave room beyond the letter itself.
        return self._create(system, convo, max_tokens=max(8000, max_tokens * 4)).strip()

    # -- Uncle's judgement (same call shape as clients.Jev.ask)
    def ask(self, state, questions):
        state_text = state if isinstance(state, str) else json.dumps(state, ensure_ascii=False, indent=1)
        prompt = f"STATE:\n{state_text[:20000]}\n\nQUESTIONS:\n{_question_text(questions)}"
        text = self._create(JUDGE_SYSTEM, [{"role": "user", "content": prompt}], max_tokens=4000,
                            output_format={"type": "json_schema", "schema": _schema(questions)})
        return to_jev(questions, json.loads(text or "{}"))
