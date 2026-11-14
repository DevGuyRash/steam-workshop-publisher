"""Package an existing Workshop content folder for a GitHub release."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import zipfile

from publisher import MAX_BYTES, MAX_FILES, release_version
from content_files import check_names, content_name, content_tree, read_regular, regular_stat


def build(content: Path, mod_id: str, version: str, output: Path, notes: str) -> None:
    release_version("v" + version)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", mod_id):
        raise ValueError("Use a mod ID containing letters, digits, underscores, or hyphens")
    if not content.is_dir():
        raise ValueError("Content must be an existing regular directory")
    regular_stat(content)
    files = {}
    for path, value in content_tree(content):
        relative = path.relative_to(content)
        if any(part in {".git", ".hg", ".svn"} or part == ".env" or part.startswith(".env.") for part in relative.parts):
            raise ValueError("Select the content folder, excluding version-control metadata and environment files")
        if stat.S_ISREG(value.st_mode):
            name = "Contents/" + relative.as_posix()
            content_name(name)
            files[name] = path
    if not files or len(files) > MAX_FILES or sum(path.stat().st_size for path in files.values()) > MAX_BYTES:
        raise ValueError("Content is empty or exceeds the package size limit")
    check_names(files)
    # Build complete artifacts before reserving the destination, and roll back
    # handled commit failures. mkdir reserves it without replacing an existing
    # (even empty) directory, unlike a directory rename on POSIX.
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"Output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".package-", dir=output.parent) as temporary:
        stage = Path(temporary)
        archive = stage / f"{mod_id}-{version}.zip"
        manifest = {}
        total = 0
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as package:
            for name, path in files.items():
                data = read_regular(path, MAX_BYTES - total)
                total += len(data)
                if total > MAX_BYTES:
                    raise ValueError("Content grew beyond the package size limit")
                member = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
                member.compress_type = zipfile.ZIP_DEFLATED
                member.external_attr = 0o100644 << 16
                package.writestr(member, data)
                manifest[name] = hashlib.sha256(data).hexdigest()
        (stage / "manifest.json").write_text(json.dumps({"id": mod_id, "version": version,
            "archiveSha256": hashlib.sha256(archive.read_bytes()).hexdigest(), "files": manifest}, indent=2) + "\n")
        (stage / "release-notes.txt").write_text(notes, encoding="utf-8")
        output.mkdir(exist_ok=False)
        owned = output.lstat()
        moved = []
        try:
            for artifact in stage.iterdir():
                destination = output / artifact.name
                with destination.open("xb") as target:
                    moved.append((destination, os.fstat(target.fileno())))
                    with artifact.open("rb") as source:
                        shutil.copyfileobj(source, target)
        except BaseException:
            # Never remove a destination that was replaced by another process.
            try:
                current = output.lstat()
                if (current.st_dev, current.st_ino) == (owned.st_dev, owned.st_ino):
                    for destination, identity in moved:
                        try:
                            current_file = destination.lstat()
                            if (current_file.st_dev, current_file.st_ino) == (identity.st_dev, identity.st_ino):
                                destination.unlink()
                        except FileNotFoundError:
                            pass
                    output.rmdir()
            except OSError:
                pass
            raise
    archive = output / archive.name
    print(f"Packaged {len(files)} files in {archive}. Attach all three files to GitHub release v{version}.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("content", type=Path)
    parser.add_argument("id")
    parser.add_argument("version")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--notes-file", type=Path)
    args = parser.parse_args()
    try:
        build(args.content, args.id, args.version,
              args.out or Path(".local/packages") / f"{args.id}-{args.version}",
              args.notes_file.read_text(encoding="utf-8") if args.notes_file else f"Release v{args.version}\n")
    except (ValueError, OSError) as error:
        parser.exit(1, str(error) + "\n")
