"""Portable content names and reads without following links or Windows junctions."""

import os
from pathlib import Path, PurePosixPath
import stat


def content_name(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    reserved = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
    if (not name or path.is_absolute() or path.as_posix() != name or ".." in path.parts
            or any(ord(char) < 32 or ord(char) == 127 for char in name)
            or any(char in name for char in '\\:<>"|?*')
            or any(part.endswith((".", " ")) or part.split(".")[0].lower() in reserved for part in path.parts)):
        raise ValueError("Content names must be portable relative paths without drives, streams, or reserved Windows names")
    return path


def check_names(names) -> None:
    seen, files, directories = {}, set(), set()
    for name in names:
        parts = content_name(name).parts
        for index in range(1, len(parts) + 1):
            prefix = "/".join(parts[:index])
            folded = prefix.casefold()
            if folded in seen and seen[folded] != prefix:
                raise ValueError("Content paths collide on a case-insensitive filesystem")
            if index < len(parts) and folded in files:
                raise ValueError("Content uses the same path as a file and a directory")
            if index < len(parts):
                directories.add(folded)
            seen[folded] = prefix
        folded = name.casefold()
        if folded in files or folded in directories:
            raise ValueError("Content contains duplicate paths or a file/directory collision")
        files.add(folded)


def regular_stat(path: Path):
    value = path.lstat()
    if stat.S_ISLNK(value.st_mode) or getattr(value, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
        raise ValueError("Content cannot contain symlinks, Windows junctions, or reparse points")
    if not (stat.S_ISDIR(value.st_mode) or stat.S_ISREG(value.st_mode)):
        raise ValueError("Content must contain only regular files and directories")
    return value


def content_tree(root: Path):
    regular_stat(root)
    for path in sorted(root.iterdir()):
        value = regular_stat(path)
        yield path, value
        if stat.S_ISDIR(value.st_mode):
            yield from content_tree(path)


def read_regular(path: Path, limit: int) -> bytes:
    before = regular_stat(path)
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("Expected a regular content file")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(path, flags), "rb") as stream:
        opened = os.fstat(stream.fileno())
        after = regular_stat(path)
        if (not stat.S_ISREG(opened.st_mode) or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino)
                or (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino)):
            raise ValueError("Content changed while opening the file")
        return stream.read(limit + 1)
