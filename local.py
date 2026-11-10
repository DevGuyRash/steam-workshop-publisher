"""Validate or publish a release in the foreground."""

import argparse
from pathlib import Path
import subprocess
import tempfile

from session import LOCAL_ROOT


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mod")
    parser.add_argument("tag")
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix="workshop-release-") as temporary:
        stage = Path(temporary) / "stage"
        subprocess.run(["python3", str(root / "publisher.py"), "prepare", "--mod", args.mod,
                        "--tag", args.tag, "--out", str(stage)], check=True)
        if args.publish:
            username_file = LOCAL_ROOT / "username"
            if not username_file.is_file():
                raise SystemExit("Run just login in your own terminal before publishing locally")
            subprocess.run(["python3", str(root / "publisher.py"), "upload", "--stage", str(stage),
                            "--steamcmd-dir", str(LOCAL_ROOT), "--username", username_file.read_text().strip()], check=True)


if __name__ == "__main__":
    main()
