"""Prepare ignored relay secrets and private Render profiles without printing keys."""
from __future__ import annotations

import argparse
from pathlib import Path
import secrets
from urllib.parse import urlsplit

from dotenv import dotenv_values


def write_profile(path: Path, values: dict[str, str]):
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("# Private server configuration; never commit or paste into chat.\n")
        for name, value in values.items():
            if "'" in value or "\n" in value or "\r" in value:
                raise ValueError("Configuration contains unsupported quoting")
            handle.write(f"{name}='{value}'\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-url")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    local_path = root / ".env.local-ai"
    if not local_path.exists():
        # Exclusive creation avoids overwriting an existing relay credential.
        with local_path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(f"ALLPS_LOCAL_RELAY_KEY='{secrets.token_urlsafe(48)}'\n")
            handle.write("ALLPS_LOCAL_MODEL='qwen3.5-4b'\n")
    local = dotenv_values(local_path)
    if len(local.get("ALLPS_LOCAL_RELAY_KEY") or "") < 32 or not local.get("ALLPS_LOCAL_MODEL"):
        raise ValueError("Existing local relay configuration is incomplete")
    print("Private relay configuration ready in .env.local-ai. No key printed.")
    if args.public_url:
        url = urlsplit(args.public_url)
        if (url.scheme != "https" or not url.hostname or not url.hostname.endswith(".trycloudflare.com")
                or url.username or url.password or url.port not in (None, 443)
                or url.path not in ("", "/") or url.query or url.fragment):
            raise ValueError("Use the HTTPS root URL returned by the Cloudflare Quick Tunnel")
        write_profile(root / ".env.local-ai-render", {
            "ALLPS_AI_BASE_URL": args.public_url.rstrip("/") + "/v1",
            "ALLPS_AI_PROVIDER": "Local LM Studio via HTTPS",
            "ALLPS_AI_MODEL": local["ALLPS_LOCAL_MODEL"],
            "ALLPS_AI_API_KEY": local["ALLPS_LOCAL_RELAY_KEY"],
            "ALLPS_AI_TIMEOUT": "180",
            "ALLPS_PROBE_TIMEOUT": "45",
        })
        amd = dotenv_values(root / ".env")
        names = ("ALLPS_AI_BASE_URL", "ALLPS_AI_PROVIDER", "ALLPS_AI_MODEL", "ALLPS_AI_API_KEY")
        if all(amd.get(name) for name in names):
            write_profile(root / ".env.amd-render", {
                **{name: amd[name] for name in names},
                "ALLPS_AI_TIMEOUT": amd.get("ALLPS_AI_TIMEOUT") or "120",
                "ALLPS_PROBE_TIMEOUT": amd.get("ALLPS_PROBE_TIMEOUT") or "15",
            })
        print("Private Render profiles saved: .env.local-ai-render and .env.amd-render.")
        print("Copy values privately into Render without the surrounding single quotes.")
        print("Existing .env and live Render settings were not changed.")


if __name__ == "__main__":
    main()
