"""Checked release journeys with fixture GitHub data and no real Steam upload."""

from contextlib import redirect_stderr, redirect_stdout
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import desktop
import local as release
import test_publisher


class LocalRelease(unittest.TestCase):
    def setUp(self):
        self.fixture = test_publisher.PublisherCLI()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.uploads = self.root / "uploads"
        environment = {**self.fixture.env, "HOME": str(self.root), "USERPROFILE": str(self.root)}
        for substitute in (patch.dict(os.environ, environment), patch.object(release, "UPLOAD_ROOT", self.uploads)):
            substitute.start()
            self.addCleanup(substitute.stop)

    def invoke(self, publish=False):
        arguments = ["local.py", "exampleowner/examplemod", "v0.1.1"]
        if publish:
            arguments += ["--publish", "--backend", "desktop"]
        with patch.object(sys, "argv", arguments):
            release.main()

    def test_dry_run_and_confirmed_success_remove_their_release_stages(self):
        created = []
        native_directory = tempfile.mkdtemp
        def directory(*args, **kwargs):
            kwargs.setdefault("dir", self.root)
            result = native_directory(*args, **kwargs)
            created.append(Path(result))
            return result
        with patch.object(release.tempfile, "mkdtemp", side_effect=directory), patch.object(desktop, "run") as backend:
            self.invoke()
        backend.assert_not_called()
        self.assertEqual(len(created), 1)
        self.assertFalse(created[0].exists())
        self.assertFalse(self.uploads.exists())
        observed = []
        def confirmed(app_id, **kwargs):
            observed.append(kwargs["content"].parent)
            self.assertEqual(app_id, "108600")
            self.assertEqual((kwargs["content"] / "mods/ExampleMod/42/mod.info").read_bytes(), b"id=ExampleMod\nmodversion=0.1.1\n")
        with patch.object(desktop, "run", side_effect=confirmed):
            self.invoke(publish=True)
        self.assertEqual(len(observed), 1)
        self.assertFalse(observed[0].parent.exists())
        self.assertEqual(list(self.uploads.iterdir()), [])

    def test_preparation_failure_cleans_its_snapshot_without_starting_a_backend(self):
        self.fixture.latest(prerelease=True)
        with patch.object(desktop, "run") as backend:
            with self.assertRaises(subprocess.CalledProcessError):
                self.invoke(publish=True)
        backend.assert_not_called()
        self.assertEqual(list(self.uploads.iterdir()), [])

    def test_upload_errors_and_interruptions_retain_and_report_the_checked_stage(self):
        for error in (RuntimeError("Upload timed out"), ValueError("Malformed callback"), SystemExit(130), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__):
                output, diagnostics = io.StringIO(), io.StringIO()
                expected = type(error) if isinstance(error, (SystemExit, KeyboardInterrupt)) else SystemExit
                with patch.object(desktop, "run", side_effect=error) as backend, redirect_stdout(output), redirect_stderr(diagnostics):
                    with self.assertRaises(expected):
                        self.invoke(publish=True)
                stage = backend.call_args.kwargs["content"].parent
                self.assertEqual((stage / "Contents/mods/ExampleMod/42/mod.info").read_bytes(), b"id=ExampleMod\nmodversion=0.1.1\n")
                self.assertTrue((stage / "stage.json").is_file())
                self.assertTrue((stage / "upload.vdf").is_file())
                self.assertEqual(stage.parent.parent, self.uploads)
                if os.name == "posix":
                    self.assertEqual(stage.parent.stat().st_mode & 0o777, 0o700)
                self.assertIn(str(stage), diagnostics.getvalue())
                self.assertIn(str(stage.parent), output.getvalue())
                self.assertNotIn("Published", output.getvalue())

    @unittest.skipUnless(os.name == "posix", "Descriptor handshake uses POSIX inherited descriptors")
    def test_external_reader_consumes_the_release_after_the_cli_owner_returns(self):
        read_fd, write_fd = os.pipe()
        process = None
        reader = """import os,pathlib,sys
os.read(int(sys.argv[2]),1)
print((pathlib.Path(sys.argv[1])/'mods/ExampleMod/42/mod.info').read_text(),end='')
"""
        def remote_reader(_app_id, **kwargs):
            nonlocal process
            process = subprocess.Popen([sys.executable, "-c", reader, str(kwargs["content"]), str(read_fd)],
                                       pass_fds=(read_fd,), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            raise RuntimeError("The release upload wait timed out")
        try:
            with patch.object(desktop, "run", side_effect=remote_reader):
                with self.assertRaises(SystemExit) as stopped:
                    self.invoke(publish=True)
            self.assertEqual(stopped.exception.code, 1)
            self.assertIsNone(process.poll())
            os.write(write_fd, b"read")
            stdout, stderr = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 0, stderr.decode())
            self.assertEqual(stdout, b"id=ExampleMod\nmodversion=0.1.1\n")
        finally:
            os.close(read_fd)
            os.close(write_fd)
            if process is not None and process.poll() is None:
                process.kill()
                process.communicate(timeout=10)


if __name__ == "__main__":
    unittest.main()
