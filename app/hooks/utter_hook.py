#!/usr/bin/env python3
"""Claude Code hook -> the Utter app (UDP 127.0.0.1:47800). Fire-and-forget: never blocks the agent.

Stop          sends the agent's last reply: the earbud reads its first sentence, and the
              language model predicts your answer from it.
Notification  sends permission prompts: ACCEPT (ka) allows (Return), BACK (jaw drop) denies (Escape).

Install: see docs/USAGE.md ("Utter with Claude Code")."""
import json
import socket
import sys

ADDR = ("127.0.0.1", 47800)


def last_reply(transcript_path):
    """Text of the last assistant message in a Claude Code transcript (JSONL)."""
    text = ""
    try:
        with open(transcript_path, encoding="utf-8") as f:
            for line in f:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if e.get("type") != "assistant":
                    continue
                content = (e.get("message") or {}).get("content") or []
                parts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
                if any(p.strip() for p in parts):
                    text = "\n".join(parts)
    except OSError:
        pass
    return text.strip()


def event(hook):
    name = hook.get("hook_event_name")
    if name == "Stop":
        text = hook.get("last_assistant_message") or last_reply(hook.get("transcript_path", ""))
        return {"type": "agent", "text": text} if text else None
    if name == "Notification":
        msg = hook.get("message", "")
        if hook.get("notification_type") == "permission_prompt" or "permission" in msg.lower():
            return {"type": "permission", "text": msg}
    return None


def main():
    try:
        ev = event(json.load(sys.stdin))
        if ev:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.sendto(json.dumps(ev).encode()[:60000], ADDR)
    except Exception:
        pass  # the app may not be running; never disturb the agent
    return 0


if __name__ == "__main__":
    sys.exit(main())
