#!/usr/bin/env python3
"""One-off: post a Director-attributed status message to a channel via webhook.

Usage:
  python3 post_director_message.py <channel_id> <persona_webhook_name> < message_body
"""
import sys
import json
import urllib.request
from pathlib import Path

ENV_FILE = Path("/home/kriisko/.config/systemd/user/openclaw-gateway.service.d/env.conf")


def _token() -> str:
    for line in ENV_FILE.read_text().splitlines():
        if line.startswith("Environment=DISCORD_BOT_TOKEN="):
            return line.replace("Environment=DISCORD_BOT_TOKEN=", "").strip()
    raise SystemExit("DISCORD_BOT_TOKEN not found")


def main() -> None:
    if len(sys.argv) < 3:
        sys.exit("usage: post_director_message.py <channel_id> <webhook_persona_name>")
    channel_id = sys.argv[1]
    webhook_name = sys.argv[2]  # e.g. "kriisko-employee-art-director"
    body = sys.stdin.read()
    if not body.strip():
        sys.exit("empty body on stdin")

    token = _token()
    UA = "DiscordBot (https://github.com/kriisko-glitch/ai-employee-factory, 1.0) Kriisko-Director"

    # Find webhook
    req = urllib.request.Request(
        f"https://discord.com/api/v10/channels/{channel_id}/webhooks",
        headers={"Authorization": f"Bot {token}", "User-Agent": UA},
    )
    hooks = json.loads(urllib.request.urlopen(req, timeout=10).read())
    hook = next((h for h in hooks if h["name"] == webhook_name), None)
    if not hook:
        sys.exit(f"no webhook named {webhook_name} on channel {channel_id}")

    # Post (chunk on 2000-char Discord limit)
    base_url = f"https://discord.com/api/webhooks/{hook['id']}/{hook['token']}?wait=true"
    chunks: list[str] = []
    rem = body
    while rem:
        if len(rem) <= 2000:
            chunks.append(rem)
            break
        cut = rem.rfind("\n", 0, 2000)
        if cut <= 0:
            cut = 2000
        chunks.append(rem[:cut])
        rem = rem[cut:].lstrip("\n")
    last_id = None
    for c in chunks:
        req = urllib.request.Request(
            base_url,
            data=json.dumps({"content": c, "username": "kriisko-director"}).encode(),
            headers={"Content-Type": "application/json", "User-Agent": UA},
            method="POST",
        )
        resp = urllib.request.urlopen(req, timeout=10)
        last_id = json.loads(resp.read()).get("id")
        print(f"posted chunk ({len(c)} chars), msg_id={last_id}")


if __name__ == "__main__":
    main()
