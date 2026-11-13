"""Validate or publish a release in the foreground."""

import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from publisher import add_backend_arguments, upload
from content_files import regular_stat
from folder import UPLOAD_ROOT
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
    if args.publish:
        UPLOAD_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
        regular_stat(UPLOAD_ROOT)
        UPLOAD_ROOT.chmod(0o700)
        work = Path(tempfile.mkdtemp(prefix="release-", dir=UPLOAD_ROOT))
    else:
        work = Path(tempfile.mkdtemp(prefix="workshop-release-"))
    retained = False
    try:
        stage = work / "stage"
        subprocess.run([sys.executable, str(root / "publisher.py"), "prepare", "--source", args.source,
                        "--tag", args.tag, "--out", str(stage)], check=True)
        if args.publish:
            print(f"Upload snapshot: {work}", flush=True)
            retained = True
            try:
                upload(stage, args.steamcmd_dir, args.username, backend=args.backend,
                       runtime_dir=args.runtime_dir, offline=args.offline)
            except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as error:
                parser.exit(1, f"Publisher stopped: {error}\n")
            retained = False
    finally:
        if retained:
            print(f"Upload snapshot retained at {work}. Checked release stage: {work / 'stage'}. "
                  "Steam may still be reading these files. Check the Workshop item and upload status "
                  "before retrying or removing this directory.", file=sys.stderr, flush=True)
        else:
            shutil.rmtree(work)


if __name__ == "__main__":
    main()
