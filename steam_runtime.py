"""Install a hash-pinned Steamworks redistributable without using game files."""

import ctypes
import hashlib
import os
from pathlib import Path
import platform
import sys
import sysconfig
import tarfile
import tempfile
import urllib.request

VERSION = "steamworks-sys-0.13.0"
SOURCE = f"https://static.crates.io/crates/steamworks-sys/{VERSION}.crate"
ARCHIVE_SHA256 = "ae139f051204a4af015d4f0ed3a1f7a51020d03a44c7cf249168c543d88131e9"
RUNTIMES = {
    "linux64": ("linux64/libsteam_api.so", "ec4797f76a206eb0af627af0f0788eb5a2eabf5dee38ee0a6affbaa44a645f4e"),
    "linuxarm64": ("linuxarm64/libsteam_api.so", "179bfb241de94c0320755b558d91edb0004f72d98bf7ad6f1147f9ada835dcbc"),
    "win64": ("win64/steam_api64.dll", "eb17909a76668cf9ae0b92a618a34a50f6c73d3a6787cb4dd8ce36a8b10bfb75"),
    "osx": ("osx/libsteam_api.dylib", "1e2282e1032851e423b501c2c483586793f1d5e11585edaae4c78d6a3abad1eb"),
}
MAX_ARCHIVE = 8 * 1024 * 1024


def runtime_root(explicit: Path | None = None) -> Path:
    return (explicit or Path(os.environ.get("WORKSHOP_RUNTIME_DIR", Path(__file__).parent / ".local/runtime"))).expanduser().absolute()


def runtime_platform() -> str:
    machine = platform.machine().lower()
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        if sys.platform == "darwin" and machine in {"x86_64", "arm64", "aarch64"}:
            return "osx"
        if sys.platform == "win32" and sysconfig.get_platform() == "win-amd64":
            return "win64"
        if sys.platform.startswith("linux"):
            if machine in {"x86_64", "amd64"}:
                return "linux64"
            if machine in {"arm64", "aarch64"}:
                return "linuxarm64"
    raise ValueError("Desktop Steam needs 64-bit Python on Windows x64, macOS Intel/Apple Silicon, or Linux x64/ARM64")


def checked_bytes(path: Path, expected: str, limit: int) -> bytes:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise ValueError("Invalid cached Steamworks runtime; remove the affected runtime cache and retry")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("Steamworks runtime checksum mismatch; remove the affected runtime cache and retry")
    return data


def install(root: Path, *, offline: bool = False) -> Path:
    target_platform = runtime_platform()
    member, expected = RUNTIMES[target_platform]
    directory = root / VERSION
    library = directory / member
    if library.exists() or library.is_symlink():
        checked_bytes(library, expected, 2 * 1024 * 1024)
        return library
    archive = directory / "source.crate"
    directory.mkdir(parents=True, exist_ok=True)
    if not archive.exists():
        if offline:
            raise ValueError("Steamworks runtime is not cached. Run desktop.py install-runtime once with network access")
        print("Installing the pinned Steamworks runtime (no Steam sign-in).", flush=True)
        with tempfile.TemporaryDirectory(prefix=".runtime-download-", dir=directory) as temporary:
            download = Path(temporary) / "source.crate"
            with urllib.request.urlopen(SOURCE, timeout=60) as response:
                data = response.read(MAX_ARCHIVE + 1)
            if len(data) > MAX_ARCHIVE or hashlib.sha256(data).hexdigest() != ARCHIVE_SHA256:
                raise ValueError("Steamworks runtime download did not match the pinned archive")
            download.write_bytes(data)
            os.replace(download, archive)
    checked_bytes(archive, ARCHIVE_SHA256, MAX_ARCHIVE)
    with tarfile.open(archive, "r:gz") as package:
        entry = package.getmember(f"{VERSION}/lib/steam/redistributable_bin/{member}")
        if not entry.isfile() or entry.size > 2 * 1024 * 1024:
            raise ValueError("Invalid Steamworks redistributable member")
        with package.extractfile(entry) as stream:
            data = stream.read()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("Steamworks redistributable checksum mismatch")
    library.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".runtime-install-", dir=library.parent) as temporary:
        candidate = Path(temporary) / library.name
        candidate.write_bytes(data)
        os.replace(candidate, library)
    return library
