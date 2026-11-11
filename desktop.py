"""Use the currently signed-in Steam desktop client. Never sign in or start Steam."""

import argparse
from contextlib import ExitStack
import ctypes as C
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from publisher import positive_id
from steam_runtime import install, runtime_root

RESULT_PREFIX = "WORKSHOP_DESKTOP_RESULT="


class UpdateResult(C.Structure):
    _layout_ = "ms"
    _pack_ = 8 if sys.platform == "win32" else 4
    _fields_ = [("result", C.c_int32), ("legal_required", C.c_bool), ("item_id", C.c_uint64)]


class Steam:
    def __init__(self, library: Path, app_id: int):
        self.library = C.CDLL(str(library))
        self.initialized = False
        try:
            if not self.call("SteamAPI_IsSteamRunning", C.c_bool, [])():
                raise RuntimeError("Steam is not running. Start the desktop client and sign in, then retry. No separate login was attempted")
            error = C.create_string_buffer(1024)
            result = self.call("SteamAPI_InitFlat", C.c_int, [C.c_void_p])(error)
            if result != 0:
                raise RuntimeError(f"Steam client initialization failed (code {result}). Check that Steam is updated, runs as the same OS user, and owns the selected app. No separate login was attempted")
            self.initialized = True
            self.user = self.call("SteamAPI_SteamUser_v023", C.c_void_p, [])()
            self.utils = self.call("SteamAPI_SteamUtils_v010", C.c_void_p, [])()
            self.ugc = self.call("SteamAPI_SteamUGC_v021", C.c_void_p, [])()
            if not self.user or not self.utils or not self.ugc:
                raise RuntimeError("The Steam client does not provide the required Workshop interfaces. Update Steam and retry")
            if not self.logged_on():
                raise RuntimeError("Steam is running but its current account is not online. Sign in through Steam and retry. No separate login was attempted")
            if self.call("SteamAPI_ISteamUtils_GetAppID", C.c_uint32, [C.c_void_p])(self.utils) != app_id:
                raise RuntimeError("Steam initialized a different application ID; refusing to publish")
        except BaseException:
            self.close()
            raise

    def call(self, name, result, arguments):
        function = getattr(self.library, name)
        function.restype, function.argtypes = result, arguments
        return function

    def close(self):
        if self.initialized:
            self.call("SteamAPI_Shutdown", None, [])()
            self.initialized = False

    def logged_on(self):
        return self.call("SteamAPI_ISteamUser_BLoggedOn", C.c_bool, [C.c_void_p])(self.user)

    def upload(self, app_id: int, item_id: int, content: Path, notes: str, timeout: float):
        handle = self.call("SteamAPI_ISteamUGC_StartItemUpdate", C.c_uint64,
                           [C.c_void_p, C.c_uint32, C.c_uint64])(self.ugc, app_id, item_id)
        if handle in (0, 2**64 - 1):
            raise RuntimeError("Steam refused the Workshop update handle. Check the app and existing item IDs")
        if not self.call("SteamAPI_ISteamUGC_SetItemContent", C.c_bool,
                         [C.c_void_p, C.c_uint64, C.c_char_p])(self.ugc, handle, str(content).encode("utf-8")):
            raise RuntimeError("Steam refused the content folder")
        call = self.call("SteamAPI_ISteamUGC_SubmitItemUpdate", C.c_uint64,
                         [C.c_void_p, C.c_uint64, C.c_char_p])(self.ugc, handle, notes.encode("utf-8"))
        if call == 0:
            raise RuntimeError("Steam refused the Workshop upload request")
        completed = self.call("SteamAPI_ISteamUtils_IsAPICallCompleted", C.c_bool,
                              [C.c_void_p, C.c_uint64, C.POINTER(C.c_bool)])
        get_result = self.call("SteamAPI_ISteamUtils_GetAPICallResult", C.c_bool,
                               [C.c_void_p, C.c_uint64, C.c_void_p, C.c_int, C.c_int, C.POINTER(C.c_bool)])
        callbacks = self.call("SteamAPI_RunCallbacks", None, [])
        failed = C.c_bool()
        deadline = time.monotonic() + timeout
        while not completed(self.utils, call, C.byref(failed)):
            if time.monotonic() >= deadline:
                raise RuntimeError("Steam upload timed out. Check the existing item's update time before retrying")
            callbacks()
            if not self.logged_on():
                raise RuntimeError("Steam went offline during upload. Check the existing item before retrying")
            time.sleep(0.1)
        result = UpdateResult()
        received = get_result(self.utils, call, C.byref(result), C.sizeof(result), 3404, C.byref(failed))
        if not received or failed.value:
            raise RuntimeError("Steam did not return a valid Workshop upload result. Check the existing item before retrying")
        if result.result != 1:
            reason = {2: "Steam reported a general failure", 8: "the app/item parameters or Workshop configuration are invalid",
                      9: "the item or content was not found", 15: "the current Steam account lacks permission or a game license",
                      16: "Steam timed out", 25: "the Workshop or account limit was exceeded", 33: "Steam could not lock the item"}.get(result.result, "Steam rejected the update")
            raise RuntimeError(f"Workshop upload failed (result {result.result}): {reason}")
        if result.item_id != item_id:
            raise RuntimeError("Steam confirmed a different item ID; inspect Workshop before retrying")
        if result.legal_required:
            raise RuntimeError("Steam received the update but requires the current account to accept the Workshop agreement at https://steamcommunity.com/sharedfiles/workshoplegalagreement")


def run(app_id: str, *, content: Path | None = None, item_id: str | None = None, notes: str = "",
        runtime: Path | None = None, offline: bool = False, timeout: float = 180) -> dict:
    app_id = positive_id(app_id, 32, "Steam application")
    if content is not None:
        item_id = positive_id(item_id, 64, "Workshop updates")
        content = content.resolve(strict=True)
        if not content.is_dir():
            raise ValueError("Choose an existing content directory")
    if "\0" in notes or len(notes.encode("utf-8")) > 65536:
        raise ValueError("Change notes exceed 64 KiB or contain a null character")
    root = runtime_root(runtime)
    install(root, offline=offline)
    cancelled = None
    previous, process = {}, None

    def cancel(signum, _frame):
        nonlocal cancelled
        cancelled = cancelled or signum

    try:
        for signum in (signal.SIGINT, signal.SIGTERM, *([signal.SIGHUP] if hasattr(signal, "SIGHUP") else [])):
            previous[signum] = signal.signal(signum, cancel)
        with tempfile.TemporaryDirectory(prefix="workshop-desktop-") as temporary, tempfile.TemporaryFile() as log, ExitStack() as cleanup:
            work = Path(temporary)
            (work / "steam_appid.txt").write_text(app_id, encoding="ascii")
            request = work / "request.json"
            request.write_text(json.dumps({"app_id": app_id, "item_id": item_id,
                "content": str(content) if content is not None else None, "notes": notes, "timeout": timeout}), encoding="utf-8")
            env = {key: value for key, value in os.environ.items() if key not in {
                "GH_TOKEN", "GITHUB_TOKEN", "SOURCE_RELEASES_TOKEN", "STEAM_SESSION_KEY", "STEAM_USERNAME",
                "STEAM_CONFIG_VDF", "LD_PRELOAD", "DYLD_INSERT_LIBRARIES"}}
            env.update(SteamAppId=app_id, SteamGameId=app_id)
            if cancelled is None:
                process = subprocess.Popen([sys.executable, "-I", "-S", str(Path(__file__).resolve()), "_worker",
                    "--request", str(request), "--runtime-dir", str(root)], cwd=work, env=env,
                    stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
                def reap_helper():
                    if process.poll() is None:
                        process.kill()
                    process.wait()
                cleanup.callback(reap_helper)
                deadline = time.monotonic() + timeout + 5
                while cancelled is None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise RuntimeError("Desktop Steam helper timed out; inspect the existing item before retrying an upload")
                    try:
                        returncode = process.wait(timeout=min(remaining, 0.1))
                        break
                    except subprocess.TimeoutExpired:
                        continue
            if cancelled is not None:
                raise SystemExit(128 + cancelled)
            log.seek(0, os.SEEK_END)
            log.seek(max(0, log.tell() - 16384))
            messages = [line.removeprefix(RESULT_PREFIX) for line in log.read().decode("utf-8", errors="replace").splitlines()
                        if line.startswith(RESULT_PREFIX)]
            if len(messages) != 1:
                raise RuntimeError("Desktop Steam helper failed without a valid result. No SteamCMD fallback was attempted")
            result = json.loads(messages[0])
            if returncode != 0 or not result.get("ok"):
                raise RuntimeError(result.get("error", "Desktop Steam failed. No SteamCMD fallback was attempted"))
            return result
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def worker(request: Path, runtime: Path):
    steam = None
    try:
        data = json.loads(request.read_text(encoding="utf-8"))
        app_id = int(positive_id(data["app_id"], 32, "Steam application"))
        steam = Steam(install(runtime, offline=True), app_id)
        if data["content"] is not None:
            item_id = int(positive_id(data["item_id"], 64, "Workshop updates"))
            steam.upload(app_id, item_id, Path(data["content"]), data["notes"], data["timeout"])
        result = {"ok": True, "backend": "desktop", "app_id": str(app_id), "uploaded": data["content"] is not None}
        code = 0
    except (ValueError, OSError, RuntimeError, AttributeError) as error:
        result, code = {"ok": False, "error": str(error)}, 1
    finally:
        if steam is not None:
            steam.close()
    print(RESULT_PREFIX + json.dumps(result), flush=True)
    return code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    probe = commands.add_parser("probe", help="Detect a usable existing login without uploading")
    probe.add_argument("--app-id", required=True)
    probe.add_argument("--offline", action="store_true", help="Use only the cached runtime; Steam itself must still be online")
    setup = commands.add_parser("install-runtime", help="Cache the pinned runtime without accessing Steam")
    internal = commands.add_parser("_worker", help=argparse.SUPPRESS)
    internal.add_argument("--request", type=Path, required=True)
    for command in (probe, setup, internal):
        command.add_argument("--runtime-dir", type=Path)
    args = parser.parse_args()
    if args.command == "_worker":
        raise SystemExit(worker(args.request, runtime_root(args.runtime_dir)))
    try:
        if args.command == "install-runtime":
            print(install(runtime_root(args.runtime_dir)))
        else:
            run(args.app_id, runtime=args.runtime_dir, offline=args.offline)
            print(f"Desktop Steam is online and ready for app {args.app_id}. No upload or separate login was attempted")
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Desktop Steam unavailable: {error}\n")


if __name__ == "__main__":
    main()
