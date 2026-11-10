"""Validate or publish an existing Workshop content folder without a registry."""

import argparse
import hashlib
import os
from pathlib import Path
import stat
import subprocess
import tempfile

from publisher import MAX_BYTES, MAX_FILES, positive_id, send_to_steam, workshop_vdf
from session import LOCAL_ROOT


def content_source(path: Path, app_id: str | None, item_id: str | None) -> tuple[Path, str, str]:
    path = path.expanduser()
    if path.is_symlink() or not path.is_dir():
        raise ValueError("Choose a regular content folder or a Project Zomboid Workshop folder")
    path = path.resolve()
    metadata = path / "workshop.txt"
    if (path / "Contents").is_dir() and metadata.is_file():
        if metadata.is_symlink() or metadata.stat().st_size > 65536:
            raise ValueError("Invalid Workshop metadata file")
        ids = [line.partition("=")[2].strip() for line in metadata.read_text(encoding="utf-8").splitlines()
               if line.startswith("id=")]
        if item_id is None:
            if len(ids) != 1:
                raise ValueError("Workshop metadata needs one existing id= or an explicit --item-id")
            item_id = ids[0]
        app_id = app_id or "108600"
        path /= "Contents"
    if app_id is None or item_id is None:
        raise ValueError("A plain content folder needs --app-id and --item-id for the existing Workshop item")
    return path, positive_id(app_id, 32, "Steam application"), positive_id(item_id, 64, "Workshop updates")


def snapshot(source: Path, destination: Path) -> tuple[int, str]:
    if source.is_symlink():
        raise ValueError("Content folder cannot be a symlink")
    destination.mkdir(mode=0o700)
    total = 0
    count = 0
    fingerprint = hashlib.sha256()
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        name = relative.as_posix()
        if "\\" in name or any(ord(char) < 32 or ord(char) == 127 for char in name):
            raise ValueError("Content contains an unsupported filename")
        if any(part in {".git", ".hg", ".svn"} or part == ".env" or part.startswith(".env.") for part in relative.parts):
            raise ValueError("Choose the packaged content folder; Git metadata and environment files cannot be uploaded")
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode) or not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
            raise ValueError("Content must contain only regular files and directories")
        if stat.S_ISDIR(mode):
            continue
        count += 1
        if count > MAX_FILES:
            raise ValueError("Content exceeds the supported file count")
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError("Content changed into a non-regular file")
            data = stream.read(MAX_BYTES - total + 1)
        total += len(data)
        if total > MAX_BYTES:
            raise ValueError("Content exceeds WORKSHOP_MAX_BYTES")
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        fingerprint.update(name.encode("utf-8") + b"\0" + hashlib.sha256(data).digest())
    if not count:
        raise ValueError("Content folder is empty")
    return count, fingerprint.hexdigest()


def publish_folder(path: Path, app_id: str | None, item_id: str | None, steamcmd_dir: Path,
                   username: str | None, notes: str, publish: bool) -> None:
    source, app_id, item_id = content_source(path, app_id, item_id)
    with tempfile.TemporaryDirectory(prefix="workshop-folder-") as temporary:
        stage = Path(temporary)
        content = stage / "Contents"
        count, fingerprint = snapshot(source, content)
        upload = stage / "upload.vdf"
        upload.write_text(workshop_vdf(app_id, item_id, content, notes), encoding="utf-8")
        print(f"Validated {count} files for Steam app {app_id}, existing Workshop item {item_id}")
        print(f"Content SHA256: {fingerprint}")
        if publish:
            if username is None:
                account_file = steamcmd_dir / "username"
                if not account_file.is_file():
                    raise ValueError("Run just login in your own terminal before publishing locally")
                username = account_file.read_text(encoding="utf-8").strip()
            send_to_steam(upload, item_id, steamcmd_dir, username)
            print(f"Published content to existing Workshop item {item_id}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--app-id")
    parser.add_argument("--item-id")
    parser.add_argument("--steamcmd-dir", type=Path, default=LOCAL_ROOT)
    parser.add_argument("--username")
    parser.add_argument("--notes-file", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--publish", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        notes = args.notes_file.read_text(encoding="utf-8") if args.notes_file else ""
        publish_folder(args.folder, args.app_id or None, args.item_id or None, args.steamcmd_dir.expanduser(),
                       args.username, notes, args.publish)
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Publisher stopped: {error}\n")


if __name__ == "__main__":
    main()
