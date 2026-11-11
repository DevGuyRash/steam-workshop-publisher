# Publish with the existing desktop Steam session

Local publishing defaults to `auto`. It tries Steamworks initialization, verifies that the current account is online, and checks the selected application ID. This detects a usable login rather than assuming a running process or cached credential file proves authentication. Steam must already be running under the same OS user, with a license for the target app and permission to update the existing item. Start or sign into Steam through its own UI when needed; the publisher never reads passwords, login caches, or Steam Guard state.

```sh
python3 desktop.py probe --app-id 108600
python3 folder.py /path/to/content --app-id 123456 --item-id 1234567890 --publish
python3 local.py owner/example-mod v1.2.3 --publish
```

On Windows, use `python` or `py -3.12` instead of `python3`. Folder publishing requires Python 3.12+ and Steam. Release publishing additionally uses your existing GitHub CLI login. No installed game, JDK, compiler, `age`, SteamCMD, or service is needed for the desktop path. A compiler is used only by the development verification fixture.

## Choose a backend

| Selection | Behavior |
| --- | --- |
| `auto` (default) | Try the current desktop Steam session. Stop if unavailable. |
| `desktop` | Explicitly require the current desktop session. |
| `steamcmd` | Explicitly use a separate Linux SteamCMD login, which can replace another session. |

Set `WORKSHOP_BACKEND` to choose a default for local commands, or pass `--backend` to override it. Specifying a SteamCMD directory or username alone does not opt into a second login. `auto` and `desktop` never fall back to SteamCMD. The cloud workflow explicitly selects SteamCMD because GitHub-hosted workers cannot access another computer's desktop session.

## Pinned runtime and offline provisioning

The publisher's Python code uses the Steamworks flat C API through the standard library's `ctypes`. Its native dependency is the Valve Steamworks redistributable carried by the published [`steamworks-sys` 0.13.0 package](https://crates.io/crates/steamworks-sys/0.13.0). This is a third-party distribution of Valve's runtime, not an official Valve download endpoint. The archive URL, SHA256, platform member names, and individual library SHA256 values are pinned in `steam_runtime.py`. The source package is used only as a data archive; no Rust code, build script, or downloaded mod code executes. Rust is not a runtime dependency.

The dependency cache defaults to `.local/runtime` beside the publisher's scripts. `--runtime-dir /path/to/cache` overrides `WORKSHOP_RUNTIME_DIR`. Only the known native member is extracted, and the library hash is checked again before every load. The publisher does not search installed games, `PATH`, or system folders for interchangeable Steam API libraries. It deliberately communicates with the existing system Steam client through the pinned runtime. This is a fixed application dependency with an external Steam service, rather than a fully isolated Steam installation. Valve's downloaded binaries retain Valve's ownership and terms; this repository's MIT license covers its own code.

```sh
python3 desktop.py install-runtime --runtime-dir /path/to/cache
python3 desktop.py probe --app-id 108600 --runtime-dir /path/to/cache --offline
python3 folder.py /path/to/content --app-id 123456 --item-id 1234567890 --publish --offline --runtime-dir /path/to/cache
```

Provision once on a connected machine, then copy that cache alongside the same publisher revision if downloads must be disabled. `--offline` disables runtime downloads; it does not make Workshop uploads possible without an online Steam session. A checksum mismatch stops instead of silently replacing a dependency. Remove the affected runtime cache and provision again to repair corruption.

| OS and Python process | Native runtime |
| --- | --- |
| Windows x64 | `win64/steam_api64.dll` |
| macOS Intel or Apple Silicon | Universal `osx/libsteam_api.dylib` |
| Linux x64 | `linux64/libsteam_api.so` |
| Linux ARM64 | `linuxarm64/libsteam_api.so`; requires a compatible accessible Steam client |

32-bit Python and native Windows ARM64 Python are rejected. An x64 Python process on Windows uses the x64 runtime. Sandboxed Steam installations may require running the publisher in a context that can access their Steam IPC; the publisher does not bypass sandbox restrictions.

## Upload behavior and failures

The native helper runs under the same Python interpreter in a temporary working directory with the selected application ID. It calls `StartItemUpdate`, `SetItemContent`, and `SubmitItemUpdate`, preserving listing metadata and required items. It does not create items, sign in, switch accounts, restart Steam, or launch a game. It waits for Steam's call result, checks the result and returned item ID, and reports a Workshop agreement requirement separately. Raw native output is withheld, and unrelated GitHub and SteamCMD secrets are excluded from the helper's environment.

The parent bounds the helper's lifetime. Cancellation or timeout kills and reaps that helper, not the user's Steam process. A received upload can finish independently of the foreground command, so inspect the item's update time before retrying an interrupted submission. There is no unattended credential refresh or automatic resubmission.

Valve documents [client initialization](https://partner.steamgames.com/doc/api/steam_api), [platform runtimes](https://partner.steamgames.com/doc/sdk/api), and [Workshop updates and results](https://partner.steamgames.com/doc/api/ISteamUGC). A game must expose compatible Workshop publishing and grant the current account the required permissions.

## Verification

The portable suite runs real folder/package commands and compiles a native C boundary fixture with Steamworks-compatible function signatures and callback packing. It covers 64-bit IDs, Unicode arguments, unavailable/offline accounts, application mismatch, denied updates, malformed completion, agreements, disconnects, timeouts, and helper cleanup without contacting Steam. Separate checks cover explicit backend selection, absent-runtime failure without SteamCMD fallback, portable paths, and native Windows junction rejection. Windows/macOS CI also installs and loads the actual hash-pinned runtime without signing in or submitting content. Linux's full suite retains the existing SteamCMD and cloud fixtures.

A no-upload probe on a real signed-in client establishes local session reuse. It does not prove a live Workshop upload or every supported game, and no real item update is part of the automated tests.
