"""Configure the shared cloud publisher using an existing local gh login."""

import argparse
import json
import subprocess
import webbrowser

from publisher import validate_source
from session import LOCAL_ROOT, login, publisher_repository


def gh(*arguments: str) -> str:
    result = subprocess.run(["gh", *arguments], check=True, capture_output=True, text=True, timeout=60)
    return result.stdout.strip()


def inspect_setup(repository: str, sources: list[str]) -> tuple[list[str], set[str], set[str]]:
    sources = sorted(set(sources))
    fields = []
    for index, source in enumerate(sources):
        validate_source(source)
        owner, name = source.split("/")
        fields.append(f"r{index}:repository(owner:{json.dumps(owner)},name:{json.dumps(name)}){{isPrivate}}")
    response = json.loads(gh("api", "graphql", "-f", "query=query{" + " ".join(fields) + "}")) if sources else {"data": {}}
    private = []
    for index, source in enumerate(sources):
        details = response["data"].get(f"r{index}")
        if details is None:
            raise ValueError(f"Your local gh login cannot inspect registered source {source}")
        if details["isPrivate"]:
            private.append(source)
    secrets = set(gh("api", f"repos/{repository}/actions/secrets", "--paginate", "--jq", ".secrets[].name").splitlines())
    variables = set(gh("api", f"repos/{repository}/actions/variables", "--paginate", "--jq", ".variables[].name").splitlines())
    return private, secrets, variables


def setup(repository: str, sources: list[str], check: bool) -> None:
    private, secrets, variables = inspect_setup(repository, sources)
    source_missing = bool(private) and "SOURCE_RELEASES_TOKEN" not in secrets
    steam_ready = "STEAM_SESSION_KEY" in secrets and "STEAM_USERNAME" in variables
    print("Your existing local gh login is working. Local publishing reuses it; no extra GitHub token is needed locally.")
    print(f"This command configures publishing on GitHub's separate cloud worker in {repository}.")
    if private:
        print("Selected private source repositories:")
        for source in private:
            print(f"  {source}")
        if source_missing:
            print("Cloud source access is missing. The cloud worker cannot use the login stored on this computer.")
            print("It needs one shared read-only token covering those private repositories.")
        else:
            print("Cloud source access is already configured; keeping the existing SOURCE_RELEASES_TOKEN.")
    else:
        print("Selected sources are public or none were requested. No extra source access token is needed.")
    print("Cloud Steam authentication is already configured." if steam_ready else "Cloud Steam authentication needs a one-time SteamCMD sign-in.")
    if check:
        print("Status only. No browser opened, credentials requested, or settings changed.")
        return
    if source_missing:
        print("Create a fine-grained token for the listed private repositories with Contents: Read-only.")
        print("This grants the cloud worker access; it does not log you into gh again or copy your local login.")
        webbrowser.open("https://github.com/settings/personal-access-tokens/new")
        print(f"Paste that token into gh's hidden prompt to store it in {repository}.")
        subprocess.run(["gh", "secret", "set", "SOURCE_RELEASES_TOKEN", "--repo", repository], check=True)
    if not steam_ready:
        login(LOCAL_ROOT, repository, github=True)
    else:
        print("Keeping the existing Steam session. To renew it, run just login --github.")
    print("Cloud setup complete. Validate a source release with just github <owner/repository> <tag>.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", help="Publisher repository owner/name; default is this checkout's GitHub remote")
    parser.add_argument("--source", action="append", default=[], help="Optional source owner/repository to inspect for private-release access")
    parser.add_argument("--check", action="store_true", help="Show required cloud setup without prompting or changing anything")
    args = parser.parse_args()
    try:
        setup(publisher_repository(args.repo), args.source, args.check)
    except (ValueError, KeyError, OSError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Could not inspect or configure the cloud publisher ({type(error).__name__}). Check gh access to the publisher and selected sources.\n")


if __name__ == "__main__":
    main()
