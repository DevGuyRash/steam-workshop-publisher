"""Producer/consumer contract journeys; fake GitHub, no Steam uploads."""
import contextlib
import io
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import test_publisher
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import package
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
