import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CloudSetupCLI(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name in ("setup_github.py", "session.py", "publisher.py"):
            shutil.copyfile(ROOT / name, self.root / name)
        gh = self.root / "gh"
        gh.write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys
root = pathlib.Path(os.environ["SETUP_FIXTURE"])
with (root / "calls.jsonl").open("a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\\n")
if sys.argv[1:3] == ["repo", "view"]:
    print("ExampleOwner/SharedPublisher")
elif sys.argv[1:3] == ["api", "graphql"]:
    print(json.dumps({"data": {"r0": {"isPrivate": os.environ["PRIVATE"] == "1"}}}))
elif sys.argv[1] == "api" and "/actions/secrets" in sys.argv[2]:
    print(os.environ["SECRET_NAMES"])
elif sys.argv[1] == "api" and "/actions/variables" in sys.argv[2]:
    print(os.environ["VARIABLE_NAMES"])
else:
    sys.exit(97)
''')
        gh.chmod(0o700)
        browser = self.root / "browser"
        browser.write_text('#!/bin/sh\ntouch "$SETUP_FIXTURE/browser-opened"\n')
        browser.chmod(0o700)
        self.env = {key: value for key, value in os.environ.items() if key != "GITHUB_REPOSITORY"}
        self.env.update(PATH=str(self.root) + os.pathsep + os.environ["PATH"],
                        SETUP_FIXTURE=str(self.root), PRIVATE="1", SECRET_NAMES="", VARIABLE_NAMES="", BROWSER=str(browser))

    def setup(self, *arguments, source=True):
        command = [sys.executable, str(self.root / "setup_github.py")]
        if source:
            command += ["--source", "ExampleOwner/ExampleMod"]
        result = subprocess.run([*command, *arguments],
                                cwd=self.root, env=self.env, stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout, [json.loads(line) for line in (self.root / "calls.jsonl").read_text().splitlines()]

    def test_check_reuses_local_login_and_explains_only_missing_cloud_access(self):
        output, calls = self.setup("--check")
        self.assertIn("Your existing local gh login is working", output)
        self.assertIn("ExampleOwner/SharedPublisher", output)
        self.assertIn("ExampleOwner/ExampleMod", output)
        self.assertIn("cloud worker cannot use the login stored on this computer", output)
        self.assertFalse((self.root / "browser-opened").exists())
        self.assertFalse(any(call[:2] in (["auth", "status"], ["secret", "set"]) for call in calls))

    def test_public_sources_need_no_token_and_existing_steam_setup_is_kept(self):
        self.env.update(PRIVATE="0", SECRET_NAMES="STEAM_SESSION_KEY", VARIABLE_NAMES="STEAM_USERNAME")
        output, calls = self.setup()
        self.assertIn("public", output)
        self.assertIn("Keeping the existing Steam session", output)
        self.assertFalse((self.root / "browser-opened").exists())
        self.assertFalse(any(call[:2] == ["secret", "set"] for call in calls))

    def test_existing_private_source_and_steam_settings_require_no_new_credentials(self):
        self.env.update(SECRET_NAMES="SOURCE_RELEASES_TOKEN\nSTEAM_SESSION_KEY", VARIABLE_NAMES="STEAM_USERNAME")
        output, calls = self.setup()
        self.assertIn("keeping the existing SOURCE_RELEASES_TOKEN", output)
        self.assertIn("Cloud setup complete", output)
        self.assertFalse((self.root / "browser-opened").exists())
        self.assertFalse(any(call[:2] == ["secret", "set"] for call in calls))

    def test_shared_setup_needs_no_mod_registration_or_source_token(self):
        self.env.update(SECRET_NAMES="STEAM_SESSION_KEY", VARIABLE_NAMES="STEAM_USERNAME")
        output, calls = self.setup(source=False)
        self.assertIn("Cloud setup complete", output)
        self.assertFalse(any(call[:2] in (["api", "graphql"], ["secret", "set"]) for call in calls))
        self.assertFalse((self.root / "browser-opened").exists())

    def test_explicit_publisher_overrides_checkout_without_code_edits(self):
        output, calls = self.setup("--check", "--repo", "AnotherOwner/Publisher")
        self.assertIn("AnotherOwner/Publisher", output)
        self.assertFalse(any(call[:2] == ["repo", "view"] for call in calls))
        self.assertTrue(any("repos/AnotherOwner/Publisher/actions/secrets" in call for call in calls))

    def test_local_steam_login_does_not_require_or_inspect_github_authentication(self):
        steam = self.root / "steamcmd"
        (steam / "config").mkdir(parents=True)
        (steam / "config/config.vdf").write_text('"fixture" "not-real-authentication"\n')
        launcher = steam / "steamcmd.sh"
        launcher.write_text("#!/bin/sh\nexit 0\n")
        launcher.chmod(0o700)
        result = subprocess.run([sys.executable, str(self.root / "session.py"), "login", "--root", str(steam)],
                                env=self.env, input="test_account\n", capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.root / "calls.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
