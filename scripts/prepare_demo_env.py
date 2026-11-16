"""Create private judge-demo credentials without overwriting an existing .env."""
from __future__ import annotations

import json
from pathlib import Path
import secrets


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    target = root / ".env"
    teachers = [
        {"teacher_id": f"TCH-{surname.upper()}", "display_name": f"{title} {surname}",
         "password": secrets.token_urlsafe(24)}
        for title, surname in (("Ms.", "Ochieng"), ("Mr.", "Banda"), ("Ms.", "Wanjiku"),
                               ("Mr.", "Otieno"), ("Mrs.", "Kamau"))
    ]
    settings = {
        "ALLPS_AI_BASE_URL": "https://api.tokenlab.amd.com/v1",
        "ALLPS_AI_PROVIDER": "AMD Token Lab",
        "ALLPS_AI_MODEL": "Gemma-4-31B-IT",
        "ALLPS_AI_API_KEY": "REPLACE_WITH_FULL_AMD_KEY",
        "ALLPS_SESSION_SECRET": secrets.token_urlsafe(48),
        "ALLPS_DB_PATH": (root / "data/runtime/hosted-demo.db").as_posix(),
        "ALLPS_SYNTHETIC_DEMO": "true",
        "ALLPS_TEACHERS_JSON": json.dumps(teachers, separators=(",", ":")),
    }
    try:
        with target.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write("# Private local configuration. Never commit this file.\n")
            for name, value in settings.items():
                handle.write(f"{name}='{value}'\n")
    except FileExistsError:
        print("Existing .env preserved. No credentials changed.")
        return
    print("Created .env with five unique demo passwords and a stable session secret.")
    print("Open .env privately in your IDE and replace ALLPS_AI_API_KEY.")
    print("For Render, copy environment values without the surrounding single quotes.")
    print("On Render, use /var/data/allps.db for ALLPS_DB_PATH.")


if __name__ == "__main__":
    main()
