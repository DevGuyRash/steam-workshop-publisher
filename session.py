"""Manage a dedicated SteamCMD session without a background service."""

import argparse
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
import json
import uuid

REPOSITORY = "DevGuyRash/steam-workshop-publisher"
STATE_TAG = "steam-session"
LOCAL_ROOT = Path.home() / ".local/share/steam-workshop-publisher/steamcmd"
MAX_STATE_BYTES = 8 * 1024 * 1024


def command(arguments, **kwargs):
    return subprocess.run(arguments, check=True, timeout=180, **kwargs)


def install(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)
    if (root / "steamcmd.sh").is_file():
        return
    with tempfile.TemporaryDirectory(prefix="steamcmd-install-") as temporary:
        archive = Path(temporary) / "steamcmd.tar.gz"
        with urllib.request.urlopen("https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz", timeout=60) as response:
            archive.write_bytes(response.read(16 * 1024 * 1024 + 1))
        if archive.stat().st_size > 16 * 1024 * 1024:
            raise ValueError("SteamCMD installer exceeds the size limit")
        with tarfile.open(archive) as package:
            package.extractall(root, filter="data")


def session_files(root: Path) -> list[Path]:
    paths = sorted((root / "config").rglob("*")) if (root / "config").exists() else []
    paths += sorted(root.glob("ssfn*"))
    files = []
    for path in paths:
        if path.is_symlink():
            raise ValueError("Steam session contains a symlink")
        if path.is_file():
            files.append(path)
    if root / "config/config.vdf" not in files:
        raise ValueError("No SteamCMD session. Run just login --github in your own terminal")
    if sum(path.stat().st_size for path in files) > MAX_STATE_BYTES:
        raise ValueError("Steam session exceeds the size limit")
    return files


def pack(root: Path, archive: Path) -> None:
    with tarfile.open(archive, "w") as package:
        for path in session_files(root):
            package.add(path, arcname=path.relative_to(root).as_posix(), recursive=False)
    archive.chmod(0o600)


def unpack(archive: Path, root: Path) -> None:
    with tarfile.open(archive) as package:
        members = package.getmembers()
        names = set()
        for entry in members:
            path = PurePosixPath(entry.name)
            allowed = entry.name.startswith("config/") or re.fullmatch(r"ssfn[0-9]+", entry.name)
            if (not allowed or not entry.isfile() or path.is_absolute() or ".." in path.parts
                    or "\\" in entry.name or entry.name in names or len(entry.name) > 512):
                raise ValueError("Invalid Steam session archive")
            names.add(entry.name)
        if len(members) > 1000 or sum(entry.size for entry in members) > MAX_STATE_BYTES:
            raise ValueError("Steam session exceeds the size limit")
        package.extractall(root, filter="data")
    for path in session_files(root):
        path.chmod(0o600)


def save(root: Path, key_file: Path, repo: str) -> None:
    with tempfile.TemporaryDirectory(prefix="steam-session-save-") as temporary:
        work = Path(temporary)
        archive = work / "session.tar"
        pack(root, archive)
        recipient = command(["age-keygen", "-y", str(key_file)], capture_output=True, text=True).stdout.strip()
        asset = "steam-session-" + uuid.uuid4().hex + ".age"
        command(["age", "-r", recipient, "-o", str(work / asset), str(archive)], stdout=subprocess.DEVNULL)
        existing = subprocess.run(["gh", "release", "view", STATE_TAG, "--repo", repo],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
        if existing.returncode:
            command(["gh", "release", "create", STATE_TAG, "--repo", repo, "--prerelease",
                     "--title", "Encrypted SteamCMD session", "--notes",
                     "{}"], stdout=subprocess.DEVNULL)
        command(["gh", "release", "upload", STATE_TAG, str(work / asset), "--repo", repo],
                stdout=subprocess.DEVNULL)
        pointer = work / "pointer.json"
        pointer.write_text(json.dumps({"asset": asset}) + "\n")
        command(["gh", "release", "edit", STATE_TAG, "--repo", repo, "--notes-file", str(pointer)],
                stdout=subprocess.DEVNULL)
    print("Encrypted SteamCMD session saved. No plaintext authentication was uploaded.")


def restore(root: Path, key_file: Path, repo: str) -> None:
    if root.exists():
        raise ValueError("Refusing to restore over an existing SteamCMD directory")
    install(root)
    with tempfile.TemporaryDirectory(prefix="steam-session-restore-") as temporary:
        work = Path(temporary)
        pointer = command(["gh", "release", "view", STATE_TAG, "--repo", repo, "--json", "body"],
                          capture_output=True, text=True).stdout
        asset = json.loads(json.loads(pointer)["body"])["asset"]
        if not re.fullmatch(r"steam-session-[a-f0-9]{32}\.age", asset):
            raise ValueError("Invalid encrypted session asset pointer")
        command(["gh", "release", "download", STATE_TAG, "--repo", repo,
                 "--pattern", asset, "--dir", temporary], stdout=subprocess.DEVNULL)
        command(["age", "-d", "-i", str(key_file), "-o", str(work / "session.tar"), str(work / asset)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        unpack(work / "session.tar", root)


def login(root: Path, repo: str, github: bool) -> None:
    username = input("Steam account name that owns the Workshop items: ").strip()
    if not re.fullmatch(r"[A-Za-z0-9_@.\-]{1,64}", username):
        raise ValueError("Invalid Steam account name")
    install(root)
    environment = dict(os.environ, HOME=str(root))
    print("Enter your password and Steam Guard code directly into SteamCMD. This program does not handle them.")
    subprocess.run([str(root / "steamcmd.sh"), "+login", username, "+quit"],
                   cwd=root, env=environment, check=True)
    session_files(root)
    (root / "username").write_text(username + "\n")
    (root / "username").chmod(0o600)
    if github:
        key_file = root / "github-session-key.txt"
        if not key_file.exists():
            command(["age-keygen", "-o", str(key_file)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if key_file.is_symlink():
            raise ValueError("Refusing a symlink for the local session encryption key")
        key_file.chmod(0o600)
        save(root, key_file, repo)
        with key_file.open("rb") as key_input:
            command(["gh", "secret", "set", "STEAM_SESSION_KEY", "--repo", repo],
                    stdin=key_input, stdout=subprocess.DEVNULL)
        command(["gh", "variable", "set", "STEAM_USERNAME", "--repo", repo, "--body", username],
                stdout=subprocess.DEVNULL)
        print("GitHub Steam authentication configured. Configure SOURCE_RELEASES_TOKEN separately for private releases.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["login", "restore", "save", "clean"])
    parser.add_argument("--root", type=Path, default=LOCAL_ROOT)
    parser.add_argument("--stage", type=Path)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", REPOSITORY))
    parser.add_argument("--github", action="store_true")
    args = parser.parse_args()
    if args.action == "login":
        login(args.root.resolve(), args.repo, args.github)
        return
    if args.action == "clean":
        runner_temp = Path(os.environ["RUNNER_TEMP"]).resolve()
        for path in (args.root, args.stage):
            if path is not None and path.exists():
                resolved = path.resolve()
                if resolved.parent != runner_temp or path.is_symlink():
                    raise ValueError("Cleanup requires a direct child of RUNNER_TEMP")
                shutil.rmtree(resolved)
        return
    key = os.environ.pop("STEAM_SESSION_KEY", "")
    if not key:
        raise ValueError("Missing STEAM_SESSION_KEY. Run just login --github in your own terminal")
    with tempfile.TemporaryDirectory(prefix="steam-key-") as temporary:
        key_file = Path(temporary) / "key.txt"
        key_file.touch(mode=0o600)
        key_file.write_text(key)
        if args.action == "restore":
            restore(args.root.resolve(), key_file, args.repo)
        else:
            save(args.root.resolve(), key_file, args.repo)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as error:
        raise SystemExit(f"Session operation failed ({type(error).__name__}). Check setup instructions; authentication details are never printed.") from None
