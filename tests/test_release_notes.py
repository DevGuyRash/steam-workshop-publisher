"""Producer/consumer contract journeys; fake GitHub, no Steam uploads."""
import contextlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import test_publisher
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import package
import desktop
from unittest.mock import patch
import publisher


class ReleaseNotesContract(unittest.TestCase):
    def test_invalid_notes_fail_before_output_or_parent_creation(self):
        for notes in ('x' * 65537, 'é' * 32769, 'x\x00y', 'x\x1fy', 'x\x7fy'):
            with self.subTest(notes=repr(notes[:8])), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                content = root / 'content'
                content.mkdir()
                (content / 'mod.info').write_text('fixture')
                output = root / 'new-parent' / 'release'
                with self.assertRaises(ValueError):
                    package.build(content, 'ExampleMod', '0.1.1', output, notes)
                self.assertFalse(output.parent.exists())
                self.assertEqual((content / 'mod.info').read_text(), 'fixture')

    def test_valid_artifacts_round_trip_through_actual_prepare_cli(self):
        for notes in ('', 'x' * 65536, 'é' * 32768, 'x' * 65534 + '\r\n',
                      'quoted "note"\\path\r\nnext\rline\tend\n'):
            with self.subTest(size=len(notes.encode('utf-8'))):
                fixture = test_publisher.PublisherCLI()
                fixture.setUp()
                try:
                    content = fixture.root / 'content'
                    content.mkdir()
                    (content / 'mod.info').write_text('fixture')
                    output = fixture.root / 'built'
                    with contextlib.redirect_stdout(io.StringIO()):
                        package.build(content, 'ExampleMod', '0.1.1', output, notes)
                    self.assertEqual((output / 'release-notes.txt').read_bytes(), notes.encode('utf-8'))
                    for artifact in output.iterdir():
                        shutil.copyfile(artifact, fixture.assets / artifact.name)
                    fixture.prepare()
                    self.assertEqual((fixture.stage / 'release-notes.txt').read_bytes(), notes.encode('utf-8'))
                    normalized = notes.replace('\r\n', '\n').replace('\r', '\n')
                    self.assertIn(publisher.vdf_string(normalized), (fixture.stage / 'upload.vdf').read_text())
                finally:
                    fixture.doCleanups()

    def test_raw_byte_limit_precedes_newline_normalization(self):
        with self.assertRaises(ValueError):
            publisher.release_notes(b'x' * 65535 + b'\r\n')
        self.assertEqual(publisher.release_notes(b'first\r\nsecond\rthird'), 'first\nsecond\nthird')

    def test_desktop_rejects_invalid_notes_before_runtime_or_helper(self):
        for notes in ("x" * 65537, "é" * 32768 + "x", "x" * 65535 + "\r\n",
                      "bad\0notes", "bad\x1fnotes", "bad\x7fnotes", "\ud800"):
            with self.subTest(prefix=repr(notes[:8])):
                with patch.object(desktop, "install") as install, \
                     patch.object(desktop.subprocess, "Popen") as helper:
                    with self.assertRaises(ValueError):
                        desktop.run("108600", notes=notes)
                install.assert_not_called()
                helper.assert_not_called()

    def test_desktop_accepts_exact_raw_boundary_before_runtime(self):
        for notes in ("x" * 65536, "é" * 32768, "x" * 65534 + "\r\n"):
            with self.subTest(size=len(notes.encode("utf-8"))):
                with patch.object(desktop, "install", side_effect=RuntimeError("runtime sentinel")) as install:
                    with self.assertRaisesRegex(RuntimeError, "runtime sentinel"):
                        desktop.run("108600", notes=notes)
                install.assert_called_once()

    def test_desktop_helper_receives_normalized_notes(self):
        notes = 'quoted "note"\\path\r\nnext\rline\tend'
        def inspect_request(command, **kwargs):
            request = Path(command[command.index("--request") + 1])
            self.assertEqual(json.loads(request.read_text())["notes"],
                             notes.replace("\r\n", "\n").replace("\r", "\n"))
            raise RuntimeError("helper sentinel")
        with patch.object(desktop, "install"), \
             patch.object(desktop.subprocess, "Popen", side_effect=inspect_request) as helper:
            with self.assertRaisesRegex(RuntimeError, "helper sentinel"):
                desktop.run("108600", notes=notes)
        helper.assert_called_once()

    def test_cli_rejects_invalid_notes_without_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            content = root / 'content'
            content.mkdir()
            (content / 'mod.info').write_text('fixture')
            notes = root / 'notes.txt'
            notes.write_bytes(b'ordinary\0invalid')
            output = root / 'release'
            result = subprocess.run([sys.executable, str(Path(package.__file__)), str(content),
                                     'ExampleMod', '0.1.1', '--notes-file', str(notes), '--out', str(output)],
                                    capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('unsupported control', result.stderr)
            self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
