"""Configure private release access and Steam through the user's own terminal."""

import subprocess
import webbrowser

from session import LOCAL_ROOT, REPOSITORY, login


def main() -> None:
    subprocess.run(["gh", "auth", "status"], check=True)
    print("Create a fine-grained GitHub token for the private source repositories only.")
    print("For AutoMindful select DevGuyRash/AutoMindful and Contents: Read-only.")
    print("Do not grant write permissions or paste your GitHub CLI login token.")
    webbrowser.open("https://github.com/settings/personal-access-tokens/new")
    print("Paste the new token only into GitHub CLI's hidden prompt below.")
    subprocess.run(["gh", "secret", "set", "SOURCE_RELEASES_TOKEN", "--repo", REPOSITORY], check=True)
    login(LOCAL_ROOT, REPOSITORY, github=True)
    print("Setup complete. Run just github automindful v0.1.1 to validate on GitHub.")


if __name__ == "__main__":
    main()
