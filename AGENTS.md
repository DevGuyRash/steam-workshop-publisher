# Steam Workshop publisher

Start with [docs/agent-quickstart.md](docs/agent-quickstart.md) when using this publisher for another mod. Follow [docs/setup.md](docs/setup.md) for release and cloud setup, and [docs/desktop.md](docs/desktop.md) for desktop Steam requirements and runtime provisioning.

- Reuse the current desktop Steam session for local uploads. When the task requires no separate sign-in, pass `--backend desktop` so an inherited `WORKSHOP_BACKEND` cannot select SteamCMD.
- Validate the packaged folder and probe the selected app before uploading. Use `--publish` only when the user's task includes a Workshop upload, and preserve explicit publication holds.
- If desktop Steam is unavailable, report the reason and let the user resolve it in Steam. Select SteamCMD or cloud publishing only when that separate-login path is requested.
- Use the packaged content and the existing app/item IDs supplied by the mod. Keep per-mod `workshop-publisher.json` files in their source repositories for release publishing. Local folder uploads need no registration or GitHub setup.
- Keep this repository's code, docs, examples, and tests independent of actual mod registrations and personal machine paths. Reuse the same publisher for other mods without adding mod-specific code.
- Never execute downloaded mod code or expose Steam authentication in logs or artifacts. Report a ready session or a passing fixture separately from a confirmed Workshop upload.
