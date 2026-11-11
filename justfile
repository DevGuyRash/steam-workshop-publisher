set positional-arguments

default:
    @just --list

# Validate the latest release without signing in to Steam.
validate mod tag:
    python3 local.py "$1" "$2"

# Publish locally through a dedicated SteamCMD login. No service is installed.
publish mod tag:
    python3 local.py "$1" "$2" --publish

# Inspect an existing PZ Workshop folder, or pass --app-id and --item-id for any game.
folder folder *args:
    python3 folder.py "$@"

# Upload an existing folder. PZ Workshop folders supply their own item ID.
publish-folder folder *args:
    python3 folder.py "$@" --publish

# Create the ZIP, manifest, and notes for a cloud release from any content folder.
package content id version *args:
    python3 package.py "$@"

# Register an existing item for cloud publishing. Application ID defaults to Zomboid.
add-mod key source id item appid='108600':
    python3 register.py "$@"

# Trigger a GitHub validation. Use github-publish to request an upload.
github mod tag:
    gh workflow run publish.yml -f mod="$1" -f tag="$2" -F publish=false

github-publish mod tag:
    gh workflow run publish.yml -f mod="$1" -f tag="$2" -F publish=true

# Sign in locally, or add --github to provision the GitHub publishing session.
login *args:
    python3 session.py login "$@"

# Configure private source access and Steam using your own visible terminal.
setup-github *args:
    python3 setup_github.py "$@"

check:
    python3 -m unittest discover -s tests -v
