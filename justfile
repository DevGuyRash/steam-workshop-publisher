set positional-arguments

default:
    @just --list

# Validate the latest release without signing in to Steam.
validate source tag *args:
    python3 local.py "$@"

# Publish using desktop Steam by default. SteamCMD requires --backend steamcmd.
publish source tag *args:
    python3 local.py "$@" --publish

# Inspect an existing PZ Workshop folder, or pass --app-id and --item-id for any game.
folder folder *args:
    python3 folder.py "$@"

# Upload an existing folder. PZ Workshop folders supply their own item ID.
publish-folder folder *args:
    python3 folder.py "$@" --publish

# Create the ZIP, manifest, and notes for a cloud release from any content folder.
package content id version *args:
    python3 package.py "$@"

# Write publishing settings into a mod's own repository. Defaults to Zomboid.
init directory id item appid='108600':
    python3 init_config.py "$@"

# Trigger a GitHub validation. Use github-publish to request an upload.
github source tag:
    gh workflow run publish.yml -f source="$1" -f tag="$2" -F publish=false

github-publish source tag:
    gh workflow run publish.yml -f source="$1" -f tag="$2" -F publish=true

# Sign in locally, or add --github to provision the GitHub publishing session.
login *args:
    python3 session.py login "$@"

# Configure private source access and Steam using your own visible terminal.
setup-github *args:
    python3 setup_github.py "$@"

# Detect an existing desktop Steam login without uploading.
probe appid *args:
    python3 desktop.py probe --app-id "$@"

check:
    python3 -m unittest discover -s tests -v
