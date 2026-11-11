# Steam Workshop publisher

Publish an existing mod folder or a checked GitHub release to Steam Workshop. Local uploads automatically try the currently signed-in desktop Steam client. No password, Steam Guard prompt, game installation, or background service is needed by this path. Windows x64, macOS Intel/Apple Silicon, and Linux x64/ARM64 have pinned native runtimes; a compatible Steam client must be running under the same OS user. Zomboid Workshop folders supply their own item ID. Other games use explicit application and existing Workshop item IDs.

This repository contains only shared publishing tools. Each mod keeps its settings in its own source repository. The cloud workflow takes a source repository and release tag; it downloads data and never executes that repository's code.

Install Python 3.12+ and sign in through your desktop Steam client. These commands use the same account. On Windows, use `python` or `py -3.12` in place of `python3`. GitHub CLI is needed for release downloads; folder uploads need only Python and Steam. `just` supplies optional POSIX-shell shortcuts.

```sh
python3 desktop.py probe --app-id 108600
python3 folder.py /path/to/Workshop/ExampleMod
python3 folder.py /path/to/Workshop/ExampleMod --publish
```

Without `--publish`, `folder.py` validates and previews without connecting to Steam. With `--publish`, it updates the existing item using desktop Steam by default. A Zomboid Workshop root supplies its `Contents` folder and `id=` from `workshop.txt`. For another game's plain content folder, provide both IDs.

```sh
python3 folder.py /path/to/content --app-id 123456 --item-id 1234567890 --publish
```

For cloud publishing, initialize settings in the mod's own checkout, package its content, and attach the three generated files to a stable GitHub release.

```sh
just init /path/to/mod-repository ExampleMod 1234567890
just package /path/to/Contents ExampleMod 1.2.3
```

Commit the generated `workshop-publisher.json` to the mod repository's default branch. The optional final argument to `init` selects another game's application ID; Zomboid's default is `108600`. The packager writes a ZIP, SHA256 manifest, and change notes under `.local/packages/ExampleMod-1.2.3`. It does not build or test the mod.

Local release commands reuse your existing `gh` login. Public sources need no extra GitHub token on the cloud worker. Inspect cloud requirements without changing settings, then configure Steam once.

```sh
just setup-github --check --source owner/example-mod
just setup-github --source owner/example-mod
just github owner/example-mod v1.2.3
just github-publish owner/example-mod v1.2.3
```

`github` requests cloud validation. `github-publish` requests an upload. Both return after dispatch; follow the run in the publisher's Actions tab. To publish the same source release locally through desktop Steam, use `python3 local.py owner/example-mod v1.2.3 --publish` or `just publish owner/example-mod v1.2.3`.

The cloud worker keeps Steam authentication in Actions secrets and age-encrypted session assets. It saves the refreshed session after each SteamCMD upload attempt. Steam logs and plaintext authentication are never uploaded. If Steam revokes a session or requires Steam Guard again, renew it with `just login --github` in your own terminal.

`--backend auto` is the local default and detects a usable desktop session through Steam's API. `--backend desktop` selects that path explicitly. Neither falls back to SteamCMD. `WORKSHOP_BACKEND` sets the default; a flag takes precedence. The tool does not read cached account credentials or start Steam. See [desktop publishing](docs/desktop.md) for runtime provenance, offline setup, and platform limits.

For headless publishing, explicitly select `--backend steamcmd` or use the cloud workflow. This existing backend is Linux-only and needs `age` plus SteamCMD's 32-bit runtime for cloud setup. It signs in separately and can replace another Steam session, including with cached credentials. Local SteamCMD publishing first needs `just login` in your own terminal. The cloud workflow always selects SteamCMD explicitly; it cannot reuse another PC's desktop session.

The release path checks the source configuration, latest stable version, archive SHA256, and every packaged file before updating an existing positive Workshop item ID. Both backends update content and change notes while preserving the listing's title, description, tags, visibility, preview, and required items. The game must support the selected Workshop API and the current account must own the required game license and have permission to update the item.

All cloud uploads share one serialized workflow with room for 100 pending requests. There are no scheduled jobs, Actions artifacts, or Actions caches. Standard GitHub-hosted workers in a public publisher repository do not consume private Actions minutes. See [GitHub billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions), [Valve's Workshop guide](https://partner.steamgames.com/doc/features/workshop/implementation?language=english), and [Valve's SteamCMD authentication guide](https://partner.steamgames.com/doc/sdk/uploading#5).
