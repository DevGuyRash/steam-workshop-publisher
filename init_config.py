"""Create publishing settings in a mod's own repository."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from publisher import Mod, validate_mod


def initialize(directory: Path, mod_id: str, item_id: str, app_id: str) -> None:
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("Choose an existing mod repository directory")
    mod = Mod(source="owner/repository", mod_id=mod_id, item_id=item_id,
              app_id=app_id, archive=mod_id + "-{version}.zip")
    validate_mod(mod)
    configuration = asdict(mod)
    del configuration["source"]
    path = directory / "workshop-publisher.json"
    if path.is_symlink():
        raise ValueError("Refusing a configuration symlink")
    if path.exists():
        if json.loads(path.read_text()) == configuration:
            print("Workshop publishing settings already match")
            return
        raise ValueError("Publishing settings already exist; review them instead of overwriting another item")
    with path.open("x", encoding="utf-8") as output:
        output.write(json.dumps(configuration, indent=2) + "\n")
    print(f"Created {path}. Commit it to the mod repository's default branch before publishing.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("mod_id")
    parser.add_argument("item_id")
    parser.add_argument("app_id", nargs="?", default="108600")
    args = parser.parse_args()
    try:
        initialize(args.directory.expanduser(), args.mod_id, args.item_id, args.app_id)
    except (ValueError, OSError) as error:
        parser.exit(1, str(error) + "\n")
