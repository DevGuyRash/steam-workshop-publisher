"""Register an existing Workshop item for manual cloud publishing."""

import argparse
from dataclasses import asdict
import json
import re

from publisher import Mod, ROOT, validate_mod


def register(key: str, source: str, mod_id: str, item: str, app_id: str) -> None:
    if not re.fullmatch(r"[a-z0-9-]+", key):
        raise ValueError("Use a lowercase registry key containing letters, digits, or hyphens")
    mod = Mod(source=source, mod_id=mod_id, item_id=item, archive=mod_id + "-{version}.zip", app_id=app_id)
    validate_mod(mod)
    path = ROOT / "mods.json"
    entries = json.loads(path.read_text())
    if key in entries:
        if Mod(**entries[key]) == mod:
            print(f"{key} is already registered with these settings")
            return
        raise ValueError("That key already maps to another item. Review mods.json instead of overwriting it")
    entries[key] = asdict(mod)
    temporary = path.with_suffix(".json.new")
    try:
        temporary.write_text(json.dumps(entries, indent=2) + "\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"Registered {key}. Review and commit mods.json, then run just github {key} v<version>.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("key")
    parser.add_argument("source")
    parser.add_argument("id")
    parser.add_argument("item")
    parser.add_argument("appid", nargs="?", default="108600")
    args = parser.parse_args()
    try:
        register(args.key, args.source, args.id, args.item, args.appid)
    except (ValueError, OSError) as error:
        parser.exit(1, str(error) + "\n")
