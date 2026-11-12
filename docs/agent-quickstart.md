# Publish another mod with the shared publisher

Use this guide from the shared publisher checkout. Supply that checkout or repository URL to the agent along with the mod's packaged content and existing Workshop item ID. The publisher needs no code changes or central registration for another mod.

The tool updates existing Workshop items. Create the first item and configure its listing through the game's supported uploader before using this update workflow. The active Steam account needs the target game license and permission to update that item.

## Use a local folder

Local folder publishing requires Python 3.12+, packaged content, and the Steam desktop client running and signed in under the same OS user. The native Steamworks runtime downloads automatically on first use and stays in the publisher's cache. This path needs no GitHub token, release assets, configuration file, SteamCMD setup, compiler, or service.

Run the following commands from the publisher checkout. On Windows, use `python` or `py -3.12` instead of `python3`. Replace the example paths with the mod's real packaged directory.

1. For a Zomboid Workshop folder containing `Contents` and an existing `id=` in `workshop.txt`, validate the content and item mapping.

   ```sh
   python3 folder.py "/path/to/Workshop/ExampleMod" --dry-run
   ```

   Expect `Validated ... files` with application ID `108600` and the existing item ID. Validation does not connect to Steam or upload anything.

2. Probe the current session for the game's application ID.

   ```sh
   python3 desktop.py probe --app-id 108600
   ```

   Expect `Desktop Steam is online and ready`. This does not upload content or open a separate login. If Steam is unavailable, resolve the reported condition in the Steam client.

3. When the user's task includes publishing, update the existing item.

   ```sh
   python3 folder.py "/path/to/Workshop/ExampleMod" --publish --backend desktop
   ```

   Expect `Published content to existing Workshop item ...` only after Steam confirms that item. Check its update time and change notes. If submission times out or is interrupted, inspect the item before retrying.

For a plain content folder, supply the real application and existing item IDs explicitly. This works for other games with compatible Workshop publishing.

```sh
python3 folder.py "/path/to/content" --app-id 123456 --item-id 1234567890 --dry-run
python3 desktop.py probe --app-id 123456
python3 folder.py "/path/to/content" --app-id 123456 --item-id 1234567890 --publish --backend desktop
```

Replace both example IDs. `--notes-file /path/to/notes.txt` adds change notes to a folder upload. Package only the intended Workshop files; repository metadata, credentials, saves, and downloaded dependencies belong outside that folder.

## Keep desktop Steam as the local default

With no override, local uploads use `auto`, which tries the current desktop session and stops if it is unavailable. It never falls back to SteamCMD. An explicit `--backend` overrides `WORKSHOP_BACKEND`. The commands above pin `desktop` so an inherited environment setting cannot request a separate login.

Keep Steam running and signed in through its own UI. The publisher does not start Steam, switch accounts, or collect login credentials. A first-use dependency download is separate from authentication. For a pre-provisioned runtime, use `--runtime-dir` or `WORKSHOP_RUNTIME_DIR`, and add `--offline` to prevent runtime downloads. See [desktop publishing](desktop.md) for supported platforms and sandbox limits.

## Use checked GitHub releases when needed

Choose the release path when the mod already distributes versioned assets or needs cloud publishing. Follow [source configuration and release setup](setup.md#configure-a-mod-in-its-own-repository). Keep `workshop-publisher.json` in the mod's source repository; the shared publisher stays unchanged.

After the source release contains its archive, manifest, and notes, validate it and publish locally with the same desktop session.

```sh
python3 local.py owner/example-mod v1.2.3
python3 local.py owner/example-mod v1.2.3 --publish --backend desktop
```

Replace the source repository and tag. This route uses your existing GitHub CLI login. Local folder publishing does not need this setup.

GitHub-hosted publishing uses a separate SteamCMD session. Configure that path only when the user requests headless or cloud publishing, following [cloud setup](setup.md#enable-the-cloud-publisher). Public source repositories need no extra source token. Private sources need the documented cloud read credential. Neither path requires per-mod code in this publisher.

See [fresh agent handoff verification](handoff-verification.md) for the exercised workflows and their limits. The trials cover preparation without publishing; live item updates remain outside that verification scope.
