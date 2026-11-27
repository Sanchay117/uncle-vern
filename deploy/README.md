# Putting Uncle on a Sprite

1. `sprite create uncle-vern`, then `sprite use uncle-vern` in this folder.
2. In the Fly dashboard, add the AgentMail, TypeSafe and Ollama Cloud connectors and give them
   access by Name Prefix `uncle`.
3. `deploy/push.sh` (runs the tests, copies the code to `~/app` on the Sprite).
4. On the Sprite (`sprite console`, and `exit` when done: an open console keeps the Sprite awake):
   - `cd ~/app && python3 -m uncle.setup check` (shows what the gateway offers; no keys needed)
   - `python3 -m uncle.setup inbox uncle.vern` and note the address
   - write `~/app/uncle.env`:
     ```
     OWNER_EMAILS=you@example.com
     UNCLE_INBOX=uncle.vern@agentmail.to
     PUBLIC_URL=https://uncle-vern-xxxx.sprites.app
     CODE_URL=https://github.com/...
     UNCLE_DB=/home/sprite/uncle-data/uncle.db
     UNCLE_MODEL=gpt-oss:120b
     ```
   - `sprite-env services create uncle --cmd bash --args /home/sprite/app/run.sh --http-port 8080`
     (after changing `uncle.env`: `sprite-env services restart uncle`)
5. `sprite config update --url-auth public` (`sprite url update` is deprecated)
6. Add a webhook for `message.received` on Uncle's inbox, pointing at `https://<url>/webhook/agentmail`.
   The Fly AgentMail connector blocks every webhooks endpoint, so do it off the Sprite: in the AgentMail
   console, or from this folder on your own machine with Uncle's inbox key:
   `read -s AGENTMAIL_API_KEY && export AGENTMAIL_API_KEY`, then
   `python3 -m uncle.setup webhook https://<url>/webhook/agentmail uncle.vern@agentmail.to`

Models
- Letters and decisions can each come from a different service. `UNCLE_DECIDER` = `typesafe` (Jev),
  `anthropic` (Claude), `ollama` (Clef) or `auto`; `UNCLE_WRITER` = `ollama`, `anthropic` or `auto`.
  `auto` picks by which connectors the Sprite has. Claude needs `python3 -m pip install anthropic`.
- `UNCLE_CLAUDE_MODEL` (default `claude-opus-5-5`), `UNCLE_CLAUDE_EFFORT` (default `low`).
- The Ollama connector blocks `/v1/systemone`, so Clef can't be reached through it today.

Notes
- `sprite file push` (CLI 2026-11-03) can report "directory ... does not exist" for a folder that
  does exist when it was made inside the Sprite. `push.sh` passes `-p`, which avoids it.
