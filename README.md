# Steam Workshop publisher

Publish an existing mod folder or a checked GitHub release to Steam Workshop. Run it locally in the foreground or manually on GitHub. Project Zomboid Workshop folders work directly. Other games use their own Steam application and existing Workshop item IDs. No local service, running game, or desktop Steam session is required by the SteamCMD publisher.

This public repository contains the shared publisher and an approved mod registry. Private mod archives stay in their source repositories. Steam authentication stays in one Actions secret and age-encrypted session assets. The workflow saves a new encrypted asset after each SteamCMD run, including failed uploads. It never prints SteamCMD logs or uploads plaintext authentication.

Standard GitHub-hosted workers in a public repository do not consume private-repository Actions minutes. This repository has no scheduled jobs and uses no Actions artifact or cache storage. Source repositories can still consume their own minutes when they build a release. See [GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions).

Install Python 3.12+, GitHub CLI, `just`, `age`, and SteamCMD's Linux 32-bit runtime. Follow [the setup guide](docs/setup.md), then sign in once and publish directly from a content folder.

```sh
just login
just folder ~/Zomboid/Workshop/MyMod
just publish-folder ~/Zomboid/Workshop/MyMod
```

A Zomboid Workshop root supplies its `Contents` folder and existing `id=` from `workshop.txt`. The `folder` command validates and previews the request. For another game's plain content folder, pass its application and existing item IDs explicitly.

```sh
just publish-folder /path/to/content --app-id 123456 --item-id 1234567890
```

Each game must support SteamCMD Workshop uploads and the signed-in account must have permission to update the item. The tool cannot remove a game's own upload restrictions. No registry or GitHub release is needed for these local commands.

For GitHub publishing, package and register a mod once, then publish a version.

```sh
just package /path/to/Contents ExampleMod 1.2.3
just add-mod example owner/repository ExampleMod 1234567890
```

Attach the three generated files under `.local/packages/ExampleMod-1.2.3` to GitHub release `v1.2.3`. Commit the registry entry. Use an optional final application ID in `add-mod` for another game. Local commands reuse your existing `gh` login. Inspect optional cloud requirements with `just setup-github --check`, then configure missing cloud access with `just setup-github` in your own terminal. Public sources need no extra source token. Private sources share one cloud read token; configured credentials are kept. Then use the same local or GitHub release commands for any registered mod.

```sh
just validate automindful v0.1.1
just publish automindful v0.1.1
just github automindful v0.1.1
just github-publish automindful v0.1.1
```

`validate` and `github` check the package without uploading to Steam. `publish` uses your dedicated local SteamCMD session. `github-publish` requests an upload through GitHub and returns after dispatch. Follow that run in the repository's Actions tab to see its result.

The release path accepts only registered sources, matching stable versions, the latest published release, and an existing positive Workshop item ID. It checks every packaged file against the release manifest before upload. It does not run source-repository code. SteamCMD updates preserve the listing's title, description, tags, visibility, and required items by omitting those fields from SteamCMD's update request.

All mods share one serialized Steam publishing workflow. Up to 100 requests can wait without replacing one another. Obsolete release requests fail the latest-release check. Steam can revoke a session or require Steam Guard again. Renew it with `just login --github` in your own terminal when that happens. Valve documents [Workshop uploads](https://partner.steamgames.com/doc/features/workshop/implementation?language=english) and [SteamCMD authentication in CI](https://partner.steamgames.com/doc/sdk/uploading#5).
