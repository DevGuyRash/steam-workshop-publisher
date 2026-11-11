# Set up local and GitHub Workshop publishing

Use this guide for an existing Steam Workshop item. Each mod owns its configuration and release assets. The shared publisher accepts a source repository and stable tag, so it needs no permanent mod registrations.

## Publish a local content folder

1. Install Python 3.12+, GitHub CLI, `just`, `age`, and the Linux 32-bit runtime required by SteamCMD. Ubuntu uses `lib32gcc-s1`; use the equivalent multilib runtime on other distributions.
2. Clone the shared publisher and enter its checkout.
3. Run `just folder /path/to/content --app-id <application-id> --item-id <existing-item-id>` to validate without uploading. For a Zomboid Workshop root containing `Contents` and `workshop.txt`, use `just folder /path/to/Workshop/ExampleMod` without either ID.
4. Run `just login` in your own terminal. Enter your Steam account login username, then your Steam password and Steam Guard response directly into SteamCMD. SteamCMD's `Password` prompt means your Steam password. GitHub credentials are not involved.
5. Run the same folder command with `publish-folder` instead of `folder`. Check the existing item's update time and change notes.

No GitHub login is needed for folder publishing. Commands run in the foreground and install no service. The dedicated SteamCMD installation lives under `~/.local/share/steam-workshop-publisher/steamcmd`. Its `HOME` is isolated there, and SteamCMD stores login state below `Steam/config/config.vdf`. Cloud restore uses that same layout. Keep the directory private and outside Git.

Local cancellation by Ctrl+C, SIGTERM, or SIGHUP stops the SteamCMD process group and waits for the direct child before returning. Authentication errors and timeouts fail the command without exposing raw Steam logs.

## Configure a mod in its own repository

1. Create the initial Workshop item through the game's supported uploader. Record its existing positive item ID. Configure its listing, visibility, and required items there.
2. From the publisher checkout, run `just init /path/to/mod-repository ExampleMod <item-id>`. Append another game's application ID when needed; the default is Zomboid's `108600`.
3. Review and commit `workshop-publisher.json` to the mod repository's default branch. Keep this file in the mod repository, outside packaged content.

The configuration has this shape.

```json
{
  "mod_id": "ExampleMod",
  "item_id": "1234567890",
  "app_id": "108600",
  "archive": "ExampleMod-{version}.zip"
}
```

The workflow input selects the source repository. Configuration cannot redirect that source. The default branch owns the current item mapping; release tags own the packaged content. The publisher rechecks the configuration and latest stable release before upload. It never creates another item when authentication or an update fails.

## Prepare a source release

1. Build and test the mod in its source repository. The publisher does not run build hooks or execute downloaded source code.
2. Select the exact Workshop content folder. For Zomboid, its files normally live under `mods/<mod_id>/...`; build-specific directories belong below that mod root.
3. Run `just package /path/to/Contents ExampleMod 1.2.3`. Add `--notes-file /path/to/notes.txt` for custom change notes.
4. Attach all three generated files from `.local/packages/ExampleMod-1.2.3` to published release `v1.2.3` in the source repository. The files are `ExampleMod-1.2.3.zip`, `manifest.json`, and `release-notes.txt`.
5. Run `just validate owner/example-mod v1.2.3` to download and check that release with your existing local `gh` login.

The ZIP contains `Contents/<relative content path>`. The manifest contains the mod ID, stable version, archive SHA256, and each member's SHA256. Source repositories with an existing verified build can produce the same format directly.

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

The packager accepts regular files and rejects symlinks, special files, Git, Mercurial, Subversion metadata, and environment files at every depth. It rejects invalid input before creating release assets. Keep game libraries, credentials, saves, and downloaded dependencies outside the chosen content directory. Drafts, prereleases, older tags, changed staged files, and mismatched hashes cannot upload through the release path.

## Enable the cloud publisher

1. Keep the shared publisher repository public to use free standard GitHub-hosted workers. Source repositories can be public or private.
2. Run `just setup-github --check --source owner/example-mod` to inspect missing cloud settings without prompts or changes. Local commands and workflow dispatch reuse your existing `gh` login.
3. Run `just setup-github --source owner/example-mod` in your own terminal. Public sources need no additional GitHub token. If a selected source is private and cloud source access is missing, the helper requests a fine-grained token with Contents read permission for selected private sources. It stores that token as `SOURCE_RELEASES_TOKEN` in the publisher repository. It does not copy your broad local login. Existing settings are kept.
4. Enter Steam authentication directly into SteamCMD when requested. Setup stores an age decryption key as Actions secret `STEAM_SESSION_KEY`, sets variable `STEAM_USERNAME`, and uploads only encrypted session state to a `steam-session` prerelease in the publisher repository.
5. Request cloud validation with `just github owner/example-mod v1.2.3`. Wait for its successful result.
6. Request an upload with `just github-publish owner/example-mod v1.2.3`. Follow that run to completion and check the same Workshop item. The local machine can be off during the cloud run.

You can make the same requests under **Actions > Publish Workshop item > Run workflow**, using the source repository and stable tag. Upload defaults to false. From the publisher checkout, follow runs with `gh run list --workflow publish.yml` and `gh run watch <run-id>`.

The built-in cloud token belongs to the publisher repository and can save encrypted session assets there. Public source releases need no separate credential. Private source access uses the optional read-only token. All items must be updateable by the Steam account used for the shared session. Use a separate publisher instance for another owner.

Forks detect their own GitHub remote without code changes. Select another destination explicitly with `just setup-github --repo owner/publisher --source owner/example-mod` or `just login --github --repo owner/publisher`. Cloud jobs use `GITHUB_REPOSITORY` automatically.

## Renew Steam authentication

Run `just login --github` in your own terminal when Steam expires the session or requires Steam Guard again. Keep the same Workshop IDs. Do not run setup concurrently with a cloud upload.

Each successful session save creates a uniquely named encrypted asset and updates an active pointer after upload. Previous encrypted assets remain for recovery. The temporary plaintext archive is removed when the command exits. The local key stays at `~/.local/share/steam-workshop-publisher/steamcmd/github-session-key.txt` with mode 600 so failed setup can be retried without losing the key. Keep it private and outside Git.

A workflow can fail after the content upload if saving the refreshed session fails. Check the named step and Workshop update time before retrying. A canceled run or revoked login may require renewed authentication. SteamCMD exit status alone does not establish publication; the tool also requires Steam's success result for the exact existing item.

## Adjust limits or retire a previous runner

The default content limit is 1 GiB across at most 10,000 files. Set `WORKSHOP_MAX_BYTES` in the local environment or publisher repository variables for a larger mod. Give the worker enough memory for the largest file and archive. Game and Steam limits still apply.

Verify a real cloud upload before claiming Steam authentication works. Local validation and fake SteamCMD tests do not establish live Steam access. Stop and unregister an obsolete dedicated runner and remove its service and installation when retiring it. Preserve unrelated or shared runners.
