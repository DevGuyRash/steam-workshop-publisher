# Steam Workshop publisher

Publish an existing mod folder or a checked GitHub release to Steam Workshop. Run it locally in the foreground or manually on GitHub. Zomboid Workshop folders supply their own item ID. Other games use explicit Steam application and existing Workshop item IDs. No local service, running game, or desktop Steam session is required by the SteamCMD publisher.

This repository contains only shared publishing tools. Each mod keeps its settings in its own source repository. The cloud workflow takes a source repository and release tag; it downloads data and never executes that repository's code.

Install Python 3.12+, GitHub CLI, `just`, `age`, and SteamCMD's Linux 32-bit runtime. Follow [the setup guide](docs/setup.md), then sign in once and publish directly from a content folder.

```sh
just login
just folder ~/Zomboid/Workshop/ExampleMod
just publish-folder ~/Zomboid/Workshop/ExampleMod
```

`folder` validates and previews the request. `publish-folder` updates the existing item. A Zomboid Workshop root supplies its `Contents` folder and `id=` from `workshop.txt`. For another game's plain content folder, provide both IDs.

```sh
just publish-folder /path/to/content --app-id 123456 --item-id 1234567890
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

`github` requests cloud validation. `github-publish` requests an upload. Both return after dispatch; follow the run in the publisher's Actions tab. To publish the same source release locally, use `just validate owner/example-mod v1.2.3` or `just publish owner/example-mod v1.2.3`.

The cloud worker keeps Steam authentication in Actions secrets and age-encrypted session assets. It saves the refreshed session after each SteamCMD upload attempt. Steam logs and plaintext authentication are never uploaded. If Steam revokes a session or requires Steam Guard again, renew it with `just login --github` in your own terminal.

The release path checks the source configuration, latest stable version, archive SHA256, and every packaged file before updating an existing positive Workshop item ID. Updates preserve the listing's title, description, tags, visibility, and required items. The game must support SteamCMD Workshop uploads and the signed-in account must have permission to update the item.

All cloud uploads share one serialized workflow with room for 100 pending requests. There are no scheduled jobs, Actions artifacts, or Actions caches. Standard GitHub-hosted workers in a public publisher repository do not consume private Actions minutes. See [GitHub billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions), [Valve's Workshop guide](https://partner.steamgames.com/doc/features/workshop/implementation?language=english), and [Valve's SteamCMD authentication guide](https://partner.steamgames.com/doc/sdk/uploading#5).
