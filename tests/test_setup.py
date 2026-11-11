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
        for name in ("setup_github.py", "session.py", "publisher.py", "content_files.py"):
            shutil.copyfile(ROOT / name, self.root / name)
        gh = self.root / "gh"
        gh.write_text('''#!/usr/bin/env python3
import json, os, pathlib, shutil, sys
root = pathlib.Path(os.environ["SETUP_FIXTURE"])
stored_file = root / "stored-secrets.json"
stored = json.loads(stored_file.read_text()) if stored_file.exists() else {}
deleted = root / "username-variable-deleted"
with (root / "calls.jsonl").open("a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\\n")
if sys.argv[1:3] == ["repo", "view"]:
    print("ExampleOwner/SharedPublisher")
elif sys.argv[1:3] == ["api", "graphql"]:
    print(json.dumps({"data": {"r0": {"isPrivate": os.environ["PRIVATE"] == "1"}}}))
elif sys.argv[1] == "api" and "/actions/secrets" in sys.argv[2]:
    print("\\n".join(sorted(set(os.environ["SECRET_NAMES"].splitlines()) | set(stored))))
elif sys.argv[1] == "api" and sys.argv[2].endswith("/actions/variables/STEAM_USERNAME"):
    if deleted.exists():
        sys.exit(1)
    print("synthetic_steam_login")
elif sys.argv[1] == "api" and "/actions/variables" in sys.argv[2]:
    names = set(os.environ["VARIABLE_NAMES"].splitlines())
    if deleted.exists():
        names.discard("STEAM_USERNAME")
    print("\\n".join(sorted(names)))
elif sys.argv[1:3] == ["secret", "set"]:
    if os.environ.get("FAIL_USERNAME_SECRET") and sys.argv[3] == "STEAM_USERNAME":
        sys.exit(7)
    stored[sys.argv[3]] = sys.stdin.read()
    stored_file.write_text(json.dumps(stored))
elif sys.argv[1:3] == ["variable", "delete"]:
    if os.environ.get("FAIL_USERNAME_DELETE"):
        sys.exit(8)
    deleted.touch()
elif sys.argv[1:3] == ["release", "view"]:
    sys.exit(0 if (root / "release").exists() else 1)
elif sys.argv[1:3] == ["release", "create"]:
    (root / "release").mkdir()
elif sys.argv[1:3] == ["release", "upload"]:
    shutil.copyfile(sys.argv[4], root / "release" / pathlib.Path(sys.argv[4]).name)
elif sys.argv[1:3] == ["release", "edit"]:
    shutil.copyfile(sys.argv[sys.argv.index("--notes-file") + 1], root / "release" / "pointer.json")
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

    def setup(self, *arguments, source=True, success=True):
        command = [sys.executable, str(self.root / "setup_github.py")]
        if source:
            command += ["--source", "ExampleOwner/ExampleMod"]
        result = subprocess.run([*command, *arguments],
                                cwd=self.root, env=self.env, stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        return result.stdout + result.stderr, [json.loads(line) for line in (self.root / "calls.jsonl").read_text().splitlines()]

    def test_check_reuses_local_login_and_explains_only_missing_cloud_access(self):
        output, calls = self.setup("--check")
        self.assertIn("Your existing local gh login is working", output)
        self.assertIn("ExampleOwner/SharedPublisher", output)
        self.assertIn("ExampleOwner/ExampleMod", output)
        self.assertIn("cloud worker cannot use the login stored on this computer", output)
        self.assertFalse((self.root / "browser-opened").exists())
        self.assertFalse(any(call[:2] in (["auth", "status"], ["secret", "set"]) for call in calls))

    def test_public_sources_need_no_token_and_existing_steam_setup_is_kept(self):
        self.env.update(PRIVATE="0", SECRET_NAMES="STEAM_SESSION_KEY\nSTEAM_USERNAME")
        output, calls = self.setup()
        self.assertIn("public", output)
        self.assertIn("Keeping the existing Steam session", output)
        self.assertFalse((self.root / "browser-opened").exists())
        self.assertFalse(any(call[:2] == ["secret", "set"] for call in calls))

    def test_existing_private_source_and_steam_settings_require_no_new_credentials(self):
        self.env.update(SECRET_NAMES="SOURCE_RELEASES_TOKEN\nSTEAM_SESSION_KEY\nSTEAM_USERNAME")
        output, calls = self.setup()
        self.assertIn("keeping the existing SOURCE_RELEASES_TOKEN", output)
        self.assertIn("Cloud setup complete", output)
        self.assertFalse((self.root / "browser-opened").exists())
        self.assertFalse(any(call[:2] == ["secret", "set"] for call in calls))

    def test_shared_setup_needs_no_mod_registration_or_source_token(self):
        self.env.update(SECRET_NAMES="STEAM_SESSION_KEY\nSTEAM_USERNAME")
        output, calls = self.setup(source=False)
        self.assertIn("Cloud setup complete", output)
        self.assertFalse(any(call[:2] in (["api", "graphql"], ["secret", "set"]) for call in calls))
        self.assertFalse((self.root / "browser-opened").exists())

    def test_legacy_username_migrates_once_without_reauthentication_or_value_logging(self):
        self.env.update(PRIVATE="0", SECRET_NAMES="STEAM_SESSION_KEY", VARIABLE_NAMES="STEAM_USERNAME")
        self.setup()
        output, calls = self.setup()
        self.assertEqual(json.loads((self.root / "stored-secrets.json").read_text())["STEAM_USERNAME"], "synthetic_steam_login")
        self.assertTrue((self.root / "username-variable-deleted").exists())
        self.assertEqual(sum(call[:3] == ["secret", "set", "STEAM_USERNAME"] for call in calls), 1)
        self.assertEqual(sum(call[:3] == ["variable", "delete", "STEAM_USERNAME"] for call in calls), 1)
        self.assertNotIn("synthetic_steam_login", output + json.dumps(calls))
        self.assertNotIn("Steam account login username", output)
        self.assertFalse((self.root / "browser-opened").exists())

    def test_legacy_username_check_is_read_only(self):
        self.env.update(PRIVATE="0", SECRET_NAMES="STEAM_SESSION_KEY", VARIABLE_NAMES="STEAM_USERNAME")
        output, calls = self.setup("--check")
        self.assertIn("migration", output)
        self.assertNotIn("SteamCMD sign-in", output)
        self.assertFalse((self.root / "stored-secrets.json").exists())
        self.assertFalse((self.root / "username-variable-deleted").exists())
        self.assertFalse(any(call[:2] in (["secret", "set"], ["variable", "delete"]) for call in calls))
        self.assertFalse(any(call[0] == "api" and call[1].endswith("/variables/STEAM_USERNAME") for call in calls))

    def test_failed_username_secret_write_preserves_legacy_variable(self):
        self.env.update(PRIVATE="0", SECRET_NAMES="STEAM_SESSION_KEY", VARIABLE_NAMES="STEAM_USERNAME", FAIL_USERNAME_SECRET="1")
        output, calls = self.setup(success=False)
        self.assertFalse((self.root / "username-variable-deleted").exists())
        self.assertFalse(any(call[:2] == ["variable", "delete"] for call in calls))
        self.assertNotIn("synthetic_steam_login", output + json.dumps(calls))

    def test_existing_username_secret_removes_legacy_variable_without_reading_its_value(self):
        self.env.update(PRIVATE="0", SECRET_NAMES="STEAM_SESSION_KEY\nSTEAM_USERNAME", VARIABLE_NAMES="STEAM_USERNAME")
        output, calls = self.setup()
        self.assertTrue((self.root / "username-variable-deleted").exists())
        self.assertFalse((self.root / "stored-secrets.json").exists())
        self.assertFalse(any(call[0] == "api" and call[1].endswith("/variables/STEAM_USERNAME") for call in calls))
        self.assertNotIn("Steam account login username", output)

    def test_retry_after_variable_delete_failure_keeps_the_new_secret_and_avoids_another_value_read(self):
        self.env.update(PRIVATE="0", SECRET_NAMES="STEAM_SESSION_KEY", VARIABLE_NAMES="STEAM_USERNAME", FAIL_USERNAME_DELETE="1")
        self.setup(success=False)
        self.assertEqual(json.loads((self.root / "stored-secrets.json").read_text())["STEAM_USERNAME"], "synthetic_steam_login")
        self.assertFalse((self.root / "username-variable-deleted").exists())
        del self.env["FAIL_USERNAME_DELETE"]
        output, calls = self.setup()
        reads = [call for call in calls if call[0] == "api" and call[1].endswith("/variables/STEAM_USERNAME")]
        self.assertEqual(len(reads), 1)
        self.assertEqual(sum(call[:3] == ["secret", "set", "STEAM_USERNAME"] for call in calls), 1)
        self.assertTrue((self.root / "username-variable-deleted").exists())
        self.assertNotIn("Steam account login username", output)

    @unittest.skipUnless(shutil.which("age") and shutil.which("age-keygen"), "age is required")
    def test_fresh_cloud_login_stores_username_only_as_a_secret_over_stdin(self):
        self.env["VARIABLE_NAMES"] = "STEAM_USERNAME"
        steam = self.root / "steamcmd"
        (steam / "Steam/config").mkdir(parents=True)
        (steam / "Steam/config/config.vdf").write_text('"fixture" "not-real-authentication"\n')
        launcher = steam / "steamcmd.sh"
        launcher.write_text("#!/bin/sh\nexit 0\n")
        launcher.chmod(0o700)
        result = subprocess.run([sys.executable, str(self.root / "session.py"), "login", "--root", str(steam),
                                 "--github", "--repo", "ExampleOwner/SharedPublisher"],
                                env=self.env, input="fresh_steam_login\n", capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        stored = json.loads((self.root / "stored-secrets.json").read_text())
        self.assertEqual(stored["STEAM_USERNAME"], "fresh_steam_login")
        self.assertIn("STEAM_SESSION_KEY", stored)
        calls = [json.loads(line) for line in (self.root / "calls.jsonl").read_text().splitlines()]
        self.assertFalse(any(call[:2] == ["variable", "set"] for call in calls))
        self.assertTrue((self.root / "username-variable-deleted").exists())
        self.assertFalse(any(call[0] == "api" and call[1].endswith("/variables/STEAM_USERNAME") for call in calls))
        self.assertNotIn("fresh_steam_login", result.stdout + result.stderr + json.dumps(calls))

    def test_explicit_publisher_overrides_checkout_without_code_edits(self):
        output, calls = self.setup("--check", "--repo", "AnotherOwner/Publisher")
        self.assertIn("AnotherOwner/Publisher", output)
        self.assertFalse(any(call[:2] == ["repo", "view"] for call in calls))
        self.assertTrue(any("repos/AnotherOwner/Publisher/actions/secrets" in call for call in calls))

    def test_local_steam_login_does_not_require_or_inspect_github_authentication(self):
        steam = self.root / "steamcmd"
        (steam / "Steam/config").mkdir(parents=True)
        (steam / "Steam/config/config.vdf").write_text('"fixture" "not-real-authentication"\n')
        launcher = steam / "steamcmd.sh"
        launcher.write_text("#!/bin/sh\nexit 0\n")
        launcher.chmod(0o700)
        result = subprocess.run([sys.executable, str(self.root / "session.py"), "login", "--root", str(steam)],
                                env=self.env, input="test_account\n", capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.root / "calls.jsonl").exists())
        self.assertIn("Steam account login username", result.stdout)
        self.assertIn("STEAM PASSWORD", result.stdout)
        self.assertIn("STEAM GUARD", result.stdout)

    def test_failed_steam_login_explains_credentials_without_changing_cloud_settings(self):
        steam = self.root / "steamcmd"
        steam.mkdir()
        launcher = steam / "steamcmd.sh"
        launcher.write_text("#!/bin/sh\nexit 7\n")
        launcher.chmod(0o700)
        result = subprocess.run([sys.executable, str(self.root / "session.py"), "login", "--root", str(steam),
                                 "--github", "--repo", "ExampleOwner/SharedPublisher"],
                                env=self.env, input="test_account\n", capture_output=True, text=True, timeout=15)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Steam sign-in failed", result.stdout)
        self.assertIn("Steam account login username and Steam password", result.stdout)
        self.assertIn("No cloud credentials were changed", result.stdout)
        self.assertFalse((steam / "username").exists())
        self.assertFalse((steam / "github-session-key.txt").exists())
        self.assertFalse((self.root / "calls.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
