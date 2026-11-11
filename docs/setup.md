# Set up local and GitHub Workshop publishing

Use this guide for any Steam Workshop mod with an existing item. Zomboid is the default application; other games specify their application ID. The same publisher supports local commands and manual GitHub runs. AutoMindful is the first registered mod.

## Prepare the source release

1. Create the Workshop item once through the game's supported uploader. Record its positive numeric item ID. Set its listing, visibility, and required items there. The shared publisher updates that item and never creates a replacement.
2. Build and test your mod in its own repository. Keep game libraries, downloaded dependencies, saves, and credentials outside the package.
3. Run `just package /path/to/content ModID 1.2.3` to create the three release files. Add `--notes-file /path/to/notes.txt` for custom change notes. Attach three assets to a stable published GitHub release named `vMAJOR.MINOR.PATCH`. Use a ZIP named `<mod_id>-<version>.zip`, `manifest.json`, and UTF-8 `release-notes.txt`.
4. Put the desired Workshop content under `Contents/` in the ZIP. For Zomboid, use `Contents/mods/<mod_id>/...`. Include native Zomboid layout such as `42/mod.info` and `common/media/...` as your mod requires. The generic publisher permits client, shared, and server mods.
5. Put the mod ID, matching version, ZIP SHA256, and each file's SHA256 in the manifest. Use lowercase hexadecimal hashes and ZIP member names as keys.

Use this manifest shape. Compute hashes from the finished archive and the exact file bytes.

```json
{
  "id": "ExampleMod",
  "version": "1.2.3",
  "archiveSha256": "<SHA256 of ExampleMod-1.2.3.zip>",
  "files": {
    "Contents/mods/ExampleMod/42/mod.info": "<SHA256 of that file>"
  }
}
```

The packager accepts regular files from any content folder and rejects symlinks, Git, Mercurial, and Subversion metadata (`.git`, `.hg`, and `.svn`), and environment files. These metadata paths are rejected at every depth, before creating release assets, just as in local folder publishing. Select only the files you intend to upload. It does not build or test your mod. AutoMindful's `tools/verify.py` builds and tests this format. Its release workflow attaches the checked assets. Wait for that build before requesting a Workshop upload. Drafts, prereleases, and an older release cannot publish through the shared publisher.

## Register another mod

1. Run `just add-mod example owner/repository ExampleMod 1234567890`. Use your own source repository, mod ID, and existing item ID. This writes an entry in `mods.json` and refuses to overwrite another mapping.
2. For Zomboid, keep the default application ID `108600`. For another game, add its application ID as the final argument. All item IDs must refer to existing items. Do not set one to zero.
3. Run `just check`, review the entry, and merge it to `main`.
4. For a private source, grant the publisher's read token access to that repository. Do not grant source write access.
5. Run `just github <key> <tag>` first. Check the passing validation run before requesting an upload.

All registered items must belong to the Steam account used by the publishing session. Use a separate publisher and session for another owner.

## Run locally

1. Install Python 3.12 or newer, GitHub CLI, `just`, `age`, and the Linux 32-bit loader and GCC runtime required by SteamCMD. On Ubuntu, the runtime package is `lib32gcc-s1`. On Arch, use the distribution's equivalent multilib packages. No game installation is needed.
2. Clone this repository and sign GitHub CLI into an account that can read the source releases.
3. For a local folder, run `just folder /path/to/content --app-id <application-id> --item-id <item-id>`. For a Zomboid Workshop root containing `Contents` and `workshop.txt`, omit both IDs. The command previews the request without uploading. For a GitHub release, use `just validate <key> <tag>`.
4. Run `just login` in your own interactive terminal. Enter the owning Steam account name, password, and Steam Guard code directly into SteamCMD. Confirm that SteamCMD reports a successful login.
5. Run `just publish-folder /path/to/content --app-id <application-id> --item-id <item-id>` for a plain folder, or `just publish-folder /path/to/Zomboid/Workshop/Mod` for an existing Zomboid Workshop root. Use `just publish <key> <tag>` for a registered release. Expect `Published` with the same existing item ID. Check the Workshop page's update time and change notes.

Local SteamCMD state lives under `~/.local/share/steam-workshop-publisher/steamcmd`. It is an application login cache, not a service. Commands run in the foreground and finish after the requested action. Keep that directory private and out of Git. The publisher captures upload logs only inside a temporary directory and removes them on exit.

## Enable GitHub publishing

Run `just setup-github` in your own terminal to open token setup, store source access through GitHub CLI's hidden prompt, and sign into SteamCMD. The equivalent individual steps follow.

1. Keep the shared publisher repository public if you want its standard hosted jobs to avoid private Actions minutes. Keep private source repositories private. Do not put plaintext Steam state or mod archives in the publisher repository.
2. For private sources, create a [fine-grained personal access token](https://github.com/settings/personal-access-tokens/new) owned by the source account. Select only the approved source repositories. Grant **Contents: Read-only**. Set an expiry you can maintain. Store it as the publisher repository's Actions secret `SOURCE_RELEASES_TOKEN`. Public-only sources do not need that secret. Do not copy your GitHub CLI login token.
3. From your local publisher checkout, run `just login --github` in your own terminal. Enter Steam authentication only into SteamCMD. The setup command creates an age key, encrypts the dedicated SteamCMD state, stores the key as Actions secret `STEAM_SESSION_KEY`, and sets variable `STEAM_USERNAME`. It uploads only encrypted state as a uniquely named `steam-session-<id>.age` asset on the `steam-session` prerelease. Its release notes select the active encrypted asset only after the upload finishes. Previous encrypted assets remain for recovery. The temporary plaintext archive is removed when setup exits. The local encryption key stays at `~/.local/share/steam-workshop-publisher/steamcmd/github-session-key.txt` with mode 600 so a failed setup can be retried without losing its key. Keep it private and out of Git.
4. Open **Actions > Publish Workshop item > Run workflow**. Select the registered mod and latest stable tag. Leave **Upload the checked release to Steam Workshop** unchecked for validation.
5. After validation passes, run the same workflow with upload enabled. The local machine can be off. GitHub downloads and validates the private release, restores the encrypted SteamCMD state, updates the mapped Workshop item, and encrypts the refreshed session back into the release asset.

You can trigger the same two GitHub modes with `just github <key> <tag>` and `just github-publish <key> <tag>`. These commands dispatch the workflow and return. Use `gh run list --workflow publish.yml --repo DevGuyRash/steam-workshop-publisher` and `gh run watch <run-id> --repo DevGuyRash/steam-workshop-publisher` to follow it. Dispatch needs write access to the publisher, not a new local background process.

For a fork, update `REPOSITORY` in `session.py` and the repository arguments in `justfile`. GitHub runs use their own `GITHUB_REPOSITORY` automatically. The built-in workflow token has Contents write permission only in the publisher so it can save encrypted session state. It has no access to another private repository. `SOURCE_RELEASES_TOKEN` supplies that separate read-only access.

## Renew authentication or retry an upload

1. If source access expires, replace `SOURCE_RELEASES_TOKEN` with a new read-only token for the same approved repositories.
2. If Steam requires authentication, run `just login --github` again in your own terminal. Keep the same Workshop IDs. This refreshes encrypted state using the retained local key and configures its GitHub secret. A failed state upload leaves the previous active asset intact. Do not run setup concurrently with a publishing workflow.
3. Retry the latest stable release with upload enabled. A retry targets the same item and same checked content.
4. If an upload succeeds but session saving fails, renew the GitHub session before the next upload. A failed workflow can mean the upload completed and only its authentication refresh failed. Check the named step and Workshop update time.

SteamCMD exit status alone does not establish an upload. The publisher also requires Steam's success result for the exact item. It fails closed on login requests, errors, timeouts, malformed archives, changed staged files, or a newer source release. It does not print raw Steam logs, so a Steam authentication problem requires a direct login in your own terminal. A canceled run or revoked login may also require renewal. On the supported Linux launcher, Ctrl+C, SIGTERM, and SIGHUP stop the active SteamCMD process group and wait for its direct child to exit. The local release and folder commands use the same cancellation path. This cannot undo an upload already accepted by Steam; inspect the existing item before retrying. SIGKILL and a host crash cannot run process cleanup.

## Verify and retire a previous runner

Run a real GitHub upload and inspect the same Workshop item before claiming the cloud authentication is working. Local package validation and fake SteamCMD checks do not establish live Steam authentication. Stop and unregister any obsolete self-hosted runner, then remove its dedicated service and installation. Do not remove shared runners or unrelated services. AutoMindful's former desktop publisher service and dedicated runner have been removed.

## Adjust package limits

The default content limit is 1 GiB across at most 10,000 files. Set environment variable `WORKSHOP_MAX_BYTES` for local commands or the repository variable of the same name for GitHub jobs when a larger mod needs it. Give the worker enough memory for the largest file and archive. Game and Steam upload limits still apply.
