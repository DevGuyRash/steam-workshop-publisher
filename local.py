"""Validate or publish a release in the foreground."""

import argparse
from pathlib import Path
import subprocess
import sys
import tempfile

from publisher import add_backend_arguments, upload
from session import LOCAL_ROOT


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    parser.add_argument("tag")
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--steamcmd-dir", type=Path, default=LOCAL_ROOT)
    parser.add_argument("--username")
    add_backend_arguments(parser)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix="workshop-release-") as temporary:
        stage = Path(temporary) / "stage"
        subprocess.run([sys.executable, str(root / "publisher.py"), "prepare", "--source", args.source,
                        "--tag", args.tag, "--out", str(stage)], check=True)
        if args.publish:
            try:
                upload(stage, args.steamcmd_dir, args.username, backend=args.backend,
                       runtime_dir=args.runtime_dir, offline=args.offline)
            except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as error:
                parser.exit(1, f"Publisher stopped: {error}\n")


if __name__ == "__main__":
    main()
