"""Private local state, always outside the public skill/repository."""
import json
import os
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]


def state_dir():
    base = Path(os.environ.get("MCD_STATE_DIR", Path.home() / ".local/state/mcdonalds-all-in-one-mcp")).expanduser().resolve()
    if base == PROJECT or PROJECT in base.parents:
        raise ValueError("MCD_STATE_DIR must be outside the public project")
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    base.chmod(0o700)
    return base


def private_write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix=".mcd-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.write("\n")
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def token():
    value = os.environ.get("MCD_MCP_TOKEN")
    if not value:
        path = Path.home() / ".config/mcdonalds-all-in-one-mcp/credentials.json"
        if path.is_file():
            value = read_json(path).get("token")
    if not value or not value.strip():
        raise ValueError("Set MCD_MCP_TOKEN or use the private credentials.json described in README.md")
    return value.strip()


def profile_get():
    p = state_dir() / "profile.json"
    return read_json(p) if p.exists() else {}


def profile_update(changes, remove=()):
    allowed = {"city", "store_preference", "budget_cents", "meal_mode", "likes", "dislikes", "drink_preference", "track_nutrition", "max_kcal", "max_sodium_mg", "min_protein_g", "language"}
    if set(changes) - allowed or set(remove) - allowed:
        raise ValueError("Unknown preference key; credentials, addresses and contact details do not belong in the profile")
    for key, value in changes.items():
        if key in {"likes", "dislikes"}:
            valid = isinstance(value, list) and all(isinstance(x, str) for x in value)
        elif key == "track_nutrition":
            valid = isinstance(value, bool)
        elif key in {"budget_cents", "max_kcal", "max_sodium_mg", "min_protein_g"}:
            import math
            valid = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0
            if key == "budget_cents":
                valid = valid and isinstance(value, int)
        else:
            valid = isinstance(value, str)
        if not valid:
            raise ValueError(f"Invalid preference value for {key}")
    profile = profile_get()
    for key in remove:
        profile.pop(key, None)
    profile.update(changes)
    private_write(state_dir() / "profile.json", profile)
    return profile
