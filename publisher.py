"""Validate source-owned mod releases and update their existing Steam Workshop items."""

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import signal
import stat
import subprocess
import tempfile
import time
import zipfile

VERSION = r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
DIGEST = re.compile(r"[0-9a-f]{64}")
MAX_BYTES = int(os.environ.get("WORKSHOP_MAX_BYTES", "1073741824"))
if MAX_BYTES < 1:
    raise ValueError("WORKSHOP_MAX_BYTES must be positive")
MAX_FILES = 10000


@dataclass(frozen=True)
class Mod:
    source: str
    mod_id: str
    item_id: str
    archive: str
    app_id: str = "108600"


def positive_id(value: str, bits: int, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]*", value) or int(value) >= 2**bits:
        raise ValueError(f"{label} requires a positive decimal ID")
    return value


def validate_source(value: str) -> None:
    if (not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+", value)
            or value.split("/")[1] in {".", ".."}):
        raise ValueError("Source repository must use owner/name")


def validate_mod(mod: Mod) -> None:
    validate_source(mod.source)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", mod.mod_id):
        raise ValueError("Invalid configured mod ID")
    positive_id(mod.item_id, 64, "Workshop updates")
    positive_id(mod.app_id, 32, "Steam application")
    if not re.fullmatch(r"[A-Za-z0-9_.-]*\{version\}[A-Za-z0-9_.-]*\.zip", mod.archive):
        raise ValueError("Configured archive must contain one {version} placeholder")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def release_version(tag: str) -> str:
    if not re.fullmatch("v" + VERSION, tag):
        raise ValueError("Tags must use stable vMAJOR.MINOR.PATCH")
    return tag[1:]


def checked_digest(value: str) -> str:
    if not DIGEST.fullmatch(value):
        raise ValueError("Expected a lowercase SHA256 digest")
    return value


def github_env() -> dict[str, str]:
    env = os.environ.copy()
    token = env.pop("SOURCE_RELEASES_TOKEN", "")
    if token:
        env["GH_TOKEN"] = token
    return env


def gh(*args: str) -> bytes:
    result = subprocess.run(["gh", *args], env=github_env(), stdin=subprocess.DEVNULL,
                            capture_output=True, timeout=120)
    if result.returncode:
        raise RuntimeError("GitHub release access failed; check the source read credential and release assets")
    return result.stdout


def configured_mod(source: str) -> Mod:
    validate_source(source)
    try:
        raw = gh("api", f"repos/{source}/contents/workshop-publisher.json",
                 "--header", "Accept: application/vnd.github.raw+json")
    except RuntimeError:
        raise RuntimeError("Cannot read workshop-publisher.json from the source default branch; initialize and commit its publishing settings, and check source access") from None
    if len(raw) > 65536:
        raise ValueError("Source Workshop configuration exceeds the size limit")
    settings = json.loads(raw)
    required = {"mod_id", "item_id", "archive"}
    if (not isinstance(settings, dict) or not required <= settings.keys() <= required | {"app_id"}
            or not all(isinstance(value, str) for value in settings.values())):
        raise ValueError("workshop-publisher.json needs string mod_id, item_id, archive, and optional app_id fields")
    mod = Mod(source=source, **settings)
    validate_mod(mod)
    return mod


def latest_release(mod: Mod, tag: str) -> None:
    release = json.loads(gh("api", f"repos/{mod.source}/releases/latest"))
    if (release.get("tag_name") != tag or release.get("draft") is not False
            or release.get("prerelease") is not False or not release.get("published_at")):
        raise ValueError("Only the latest published stable source release may update Workshop")


def package_path(name: str, mod: Mod) -> PurePosixPath:
    path = PurePosixPath(name)
    if (not isinstance(name, str) or "\\" in name or any(ord(c) < 32 or ord(c) == 127 for c in name)
            or path.is_absolute() or path.as_posix() != name or ".." in path.parts
            or path.parts[:1] != ("Contents",) or len(path.parts) < 2):
        raise ValueError("Package members must be normal files under Contents/")
    return path


def manifest_files(manifest: dict, mod: Mod, version: str) -> dict[str, str]:
    if manifest.get("id") != mod.mod_id or manifest.get("version") != version:
        raise ValueError("Manifest identity does not match the source mod and release tag")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files or len(files) > MAX_FILES:
        raise ValueError("Manifest must contain a bounded, nonempty file map")
    for name, expected in files.items():
        package_path(name, mod)
        checked_digest(expected)
    return files


def vdf_string(value: str) -> str:
    if any(ord(c) < 32 and c not in "\n\t" or ord(c) == 127 for c in value):
        raise ValueError("Workshop change notes contain unsupported control characters")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t") + '"'


def workshop_vdf(app_id: str, item_id: str, content: Path, notes: str) -> str:
    values = {"appid": app_id, "publishedfileid": item_id,
              "contentfolder": str(content), "changenote": notes.replace("\r\n", "\n").replace("\r", "\n")}
    return '"workshopitem"\n{\n' + "".join(f"  {vdf_string(key)} {vdf_string(value)}\n" for key, value in values.items()) + "}\n"


def vdf(mod: Mod, stage: Path, notes: str) -> str:
    return workshop_vdf(mod.app_id, mod.item_id, stage / "Contents", notes)


def prepare(source: str, tag: str, archive_hash: str | None, notes_hash: str | None, out: Path) -> None:
    version = release_version(tag)
    mod = configured_mod(source)
    if archive_hash is not None:
        checked_digest(archive_hash)
    if notes_hash is not None:
        checked_digest(notes_hash)
    out = out.absolute()
    if out.exists() or out.is_symlink():
        raise ValueError("The output staging directory must not exist")
    latest_release(mod, tag)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".workshop-stage-", dir=out.parent) as temporary:
        stage = Path(temporary) / "stage"
        stage.mkdir(mode=0o700)
        downloads = Path(temporary) / "downloads"
        downloads.mkdir(mode=0o700)
        archive_name = mod.archive.format(version=version)
        gh("release", "download", tag, "--repo", mod.source, "--dir", str(downloads),
           "--pattern", archive_name, "--pattern", "manifest.json", "--pattern", "release-notes.txt")
        archive = downloads / archive_name
        manifest_path = downloads / "manifest.json"
        notes_path = downloads / "release-notes.txt"
        if archive.stat().st_size > MAX_BYTES or manifest_path.stat().st_size > 2 * 1024 * 1024 or notes_path.stat().st_size > 65536:
            raise ValueError("Release assets exceed the supported size")
        actual_archive_hash = digest(archive.read_bytes())
        actual_notes_hash = digest(notes_path.read_bytes())
        if ((archive_hash is not None and actual_archive_hash != archive_hash)
                or (notes_hash is not None and actual_notes_hash != notes_hash)):
            raise ValueError("Release assets differ from the passing source build")
        archive_hash, notes_hash = actual_archive_hash, actual_notes_hash
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("archiveSha256") != archive_hash:
            raise ValueError("Archive differs from its manifest")
        files = manifest_files(manifest, mod, version)
        with zipfile.ZipFile(archive) as package:
            members = package.infolist()
            if len(members) != len(files) or {info.filename for info in members} != set(files):
                raise ValueError("ZIP members must exactly match the manifest")
            if sum(info.file_size for info in members) > MAX_BYTES:
                raise ValueError("Expanded package exceeds the supported size")
            for info in members:
                path = package_path(info.filename, mod)
                mode = info.external_attr >> 16
                if info.is_dir() or stat.S_ISLNK(mode) or stat.S_IFMT(mode) not in (0, stat.S_IFREG):
                    raise ValueError("ZIP members must be regular files")
                data = package.read(info)
                if digest(data) != files[info.filename]:
                    raise ValueError("ZIP member differs from its manifest")
                destination = stage.joinpath(*path.parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)
        notes = notes_path.read_text(encoding="utf-8")
        (stage / "release-notes.txt").write_bytes(notes_path.read_bytes())
        (stage / "manifest.json").write_bytes(manifest_path.read_bytes())
        (stage / "stage.json").write_text(json.dumps({"source": mod.source, "tag": tag,
            "configuration": asdict(mod),
            "archive_sha256": archive_hash, "notes_sha256": notes_hash}) + "\n", encoding="utf-8")
        (stage / "upload.vdf").write_text(vdf(mod, out, notes), encoding="utf-8")
        stage.rename(out)
    print(f"Prepared {mod.source} {tag} for existing Workshop item {mod.item_id}")


def checked_stage(stage: Path) -> tuple[Mod, str]:
    stage = stage.absolute()
    metadata = json.loads((stage / "stage.json").read_text(encoding="utf-8"))
    mod = configured_mod(metadata["source"])
    if metadata["configuration"] != asdict(mod):
        raise ValueError("Source Workshop configuration changed after staging")
    version = release_version(metadata["tag"])
    manifest = json.loads((stage / "manifest.json").read_text(encoding="utf-8"))
    files = manifest_files(manifest, mod, version)
    if manifest.get("archiveSha256") != checked_digest(metadata["archive_sha256"]):
        raise ValueError("Staging archive identity changed")
    expected = set(files) | {"stage.json", "manifest.json", "release-notes.txt", "upload.vdf"}
    actual = set()
    for path in stage.rglob("*"):
        if path.is_symlink():
            raise ValueError("Staging contains a symlink")
        if path.is_file():
            actual.add(path.relative_to(stage).as_posix())
    if actual != expected:
        raise ValueError("Staging file set changed")
    for name, expected_hash in files.items():
        if digest((stage / name).read_bytes()) != expected_hash:
            raise ValueError("Staging content changed")
    notes_bytes = (stage / "release-notes.txt").read_bytes()
    if digest(notes_bytes) != checked_digest(metadata["notes_sha256"]):
        raise ValueError("Staging change notes changed")
    if (stage / "upload.vdf").read_text(encoding="utf-8") != vdf(mod, stage, notes_bytes.decode("utf-8")):
        raise ValueError("Workshop upload configuration changed")
    return mod, metadata["tag"]


def send_to_steam(vdf_path: Path, item_id: str, steamcmd_dir: Path, username: str, timeout: float = 180) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_@.\-]{1,64}", username):
        raise ValueError("Invalid Steam account name")
    launcher = steamcmd_dir.absolute() / "steamcmd.sh"
    if not launcher.is_file():
        raise ValueError("SteamCMD is not installed in the supplied directory")
    env = {key: value for key, value in os.environ.items()
           if key not in {"GH_TOKEN", "GITHUB_TOKEN", "SOURCE_RELEASES_TOKEN", "STEAM_SESSION_KEY"}}
    env["HOME"] = str(launcher.parent)
    # The supported SteamCMD launcher is POSIX/Linux. Record cancellation rather
    # than raising inside Popen, so a signal cannot lose an already-spawned child.
    cancelled = None
    previous = {}
    process = None

    def cancel(signum, _frame):
        nonlocal cancelled
        if cancelled is None:
            cancelled = signum

    try:
        for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            previous[signum] = signal.signal(signum, cancel)
        with tempfile.TemporaryFile(mode="w+b") as log:
            if cancelled is not None:
                return
            try:
                process = subprocess.Popen([str(launcher), "+@ShutdownOnFailedCommand", "1", "+@NoPromptForPassword", "1",
                    "+login", username, "+workshop_build_item", str(vdf_path.absolute()), "+quit"],
                    cwd=launcher.parent, env=env, stdin=subprocess.DEVNULL, stdout=log,
                    stderr=subprocess.STDOUT, start_new_session=True)
                deadline = time.monotonic() + timeout
                while cancelled is None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise RuntimeError("SteamCMD timed out; renew the publishing session if Steam authentication expired")
                    try:
                        returncode = process.wait(timeout=min(remaining, 0.1))
                        break
                    except subprocess.TimeoutExpired:
                        continue
                if cancelled is not None:
                    return
            except OSError as error:
                raise RuntimeError("SteamCMD could not start; check its installed runtime dependencies") from error
            log.seek(0)
            output = log.read().decode("utf-8", errors="replace")
        success = re.search(r"Success\.\s+Published item\s+" + re.escape(item_id) + r"(?:\D|$)", output)
        failure = re.search(r"ERROR!|Login Failure|Invalid Password|Not logged on|Failed to update workshop item", output, re.IGNORECASE)
        if returncode != 0 or not success or failure:
            raise RuntimeError("SteamCMD upload failed; renew the publishing session or check item ownership. Steam output is withheld")
    finally:
        try:
            if process is not None and (cancelled is not None or process.poll() is None):
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)
        if cancelled is not None:
            raise SystemExit(128 + cancelled)


def upload(stage: Path, steamcmd_dir: Path, username: str) -> None:
    mod, tag = checked_stage(stage)
    latest_release(mod, tag)
    send_to_steam(stage / "upload.vdf", mod.item_id, steamcmd_dir, username)
    print(f"Published {tag} to existing Workshop item {mod.item_id}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare_parser = commands.add_parser("prepare")
    prepare_parser.add_argument("--source", required=True, help="Source repository owner/name")
    prepare_parser.add_argument("--tag", required=True)
    prepare_parser.add_argument("--archive-sha256")
    prepare_parser.add_argument("--notes-sha256")
    prepare_parser.add_argument("--out", type=Path, required=True)
    upload_parser = commands.add_parser("upload")
    upload_parser.add_argument("--stage", type=Path, required=True)
    upload_parser.add_argument("--steamcmd-dir", type=Path, required=True)
    upload_parser.add_argument("--username", required=True)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            prepare(args.source, args.tag, args.archive_sha256, args.notes_sha256, args.out)
        else:
            upload(args.stage, args.steamcmd_dir, args.username)
    except (ValueError, KeyError, TypeError, OSError, RuntimeError, zipfile.BadZipFile, subprocess.SubprocessError) as error:
        parser.exit(1, f"Publisher stopped: {error}\n")


if __name__ == "__main__":
    main()
