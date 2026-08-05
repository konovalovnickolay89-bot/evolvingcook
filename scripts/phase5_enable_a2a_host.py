#!/usr/bin/env python3
"""Phase 5 secrets + Hermes A2A enable (no secret echo). Run once on host."""
from __future__ import annotations

import os
import re
import secrets
from pathlib import Path

COOK_ENV = Path("/home/discovery-system/src/evolving-cook/.env")
HERMES_ENV = Path("/home/discovery-system/.hermes/.env")
HERMES_CFG = Path("/home/discovery-system/.hermes/config.yaml")


def upsert_env(path: Path, updates: dict[str, str]) -> None:
    lines: list[str] = []
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
    keys = set(updates)
    out: list[str] = []
    seen: set[str] = set()
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            out.append(line)
            continue
        k = line.split("=", 1)[0].strip()
        if k in keys:
            out.append(f"{k}={updates[k]}")
            seen.add(k)
        else:
            out.append(line)
    for k, v in updates.items():
        if k not in seen:
            out.append(f"{k}={v}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def enable_a2a_yaml(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    # If a2a already present under platforms, force enabled+port via line surgery
    if re.search(r"(?m)^    a2a:\s*$", text):
        # ensure enabled true and port 9900 nearby
        def repl_block(m: re.Match) -> str:
            return (
                "    a2a:\n"
                "      enabled: true\n"
                "      extra:\n"
                "        port: 9900\n"
            )

        text2, n = re.subn(
            r"(?ms)^    a2a:\n(?:      .*\n)*",
            repl_block,
            text,
            count=1,
        )
        if n:
            path.write_text(text2, encoding="utf-8")
            print("a2a_block_replaced")
            return
    # Insert after `  platforms:`
    m = re.search(r"(?m)^  platforms:\s*$", text)
    if not m:
        raise SystemExit("gateway.platforms not found in config.yaml")
    insert = (
        "    a2a:\n"
        "      enabled: true\n"
        "      extra:\n"
        "        port: 9900\n"
    )
    idx = m.end()
    # skip newline
    if idx < len(text) and text[idx] == "\n":
        idx += 1
    text2 = text[:idx] + insert + text[idx:]
    path.write_text(text2, encoding="utf-8")
    print("a2a_block_inserted")


def main() -> None:
    a2a_token = secrets.token_hex(32)
    push_secret = secrets.token_hex(32)

    upsert_env(
        COOK_ENV,
        {
            "APP_VERSION": "0.1.12",
            "CONTRACT_VERSION": "0.1.12",
            "A2A_TOKEN": a2a_token,
            "WEBHOOK_SECRET": push_secret,
            "A2A_BASE_URL": "http://127.0.0.1:9900",
            "A2A_PUSH_CALLBACK_URL": "http://127.0.0.1:8000/api/internal/agent-events",
            "A2A_INTERNAL_LOOPBACK_ONLY": "true",
        },
    )
    print(
        f"cook_env: A2A_TOKEN=SET len={len(a2a_token)} "
        f"WEBHOOK_SECRET=SET len={len(push_secret)} version=0.1.12"
    )

    upsert_env(
        HERMES_ENV,
        {
            "A2A_PEER_TOKENS": f"evolving-cook:{a2a_token}",
            "A2A_PUSH_SECRET": push_secret,
            "A2A_PORT": "9900",
            "A2A_HOST": "127.0.0.1",
        },
    )
    print(
        f"hermes_env: A2A_PEER_TOKENS=SET len={len('evolving-cook:')+len(a2a_token)} "
        f"A2A_PUSH_SECRET=SET len={len(push_secret)} A2A_HOST=127.0.0.1 A2A_PORT=9900"
    )

    enable_a2a_yaml(HERMES_CFG)
    # verify without dumping secrets
    cfg = HERMES_CFG.read_text(encoding="utf-8")
    assert "a2a:" in cfg and "enabled: true" in cfg and "9900" in cfg
    print("hermes_config_a2a_ok")


if __name__ == "__main__":
    main()
