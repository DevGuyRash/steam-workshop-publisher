"""Failure injection for local packaging; no publication or network access."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import package


class PackageRecovery(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.content = self.root / 'content'
        self.content.mkdir()
        (self.content / 'mod.txt').write_text('original')
        self.output = self.root / 'nested' / 'release'

    def build(self):
        package.build(self.content, 'Example', '1.2.3', self.output, 'notes')

    def assert_retry(self):
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.output.parent.glob('.package-*')), [])
        self.assertEqual((self.content / 'mod.txt').read_text(), 'original')
        self.build()
        self.assertEqual({p.name for p in self.output.iterdir()},
                         {'Example-1.2.3.zip', 'manifest.json', 'release-notes.txt'})

    def test_read_and_archive_failures_are_retryable(self):
        for target in ('package.read_regular', 'package.zipfile.ZipFile.writestr'):
            with self.subTest(target=target):
                with patch(target, side_effect=OSError('injected')):
                    with self.assertRaisesRegex(OSError, 'injected'):
                        self.build()
                self.assert_retry()
                for p in self.output.iterdir():
                    p.unlink()
                self.output.rmdir()

    def test_metadata_failures_are_retryable(self):
        original = Path.write_text
        for filename in ('manifest.json', 'release-notes.txt'):
            with self.subTest(filename=filename):
                def write(path, *args, **kwargs):
                    if path.name == filename:
                        raise OSError('injected')
                    return original(path, *args, **kwargs)
                with patch.object(Path, 'write_text', write):
                    with self.assertRaisesRegex(OSError, 'injected'):
                        self.build()
                self.assert_retry()
                for p in self.output.iterdir():
                    p.unlink()
                self.output.rmdir()

    def test_existing_destination_is_untouched(self):
        self.output.mkdir(parents=True)
        (self.output / 'foreign').write_text('keep')
        with self.assertRaises(FileExistsError):
            self.build()
        self.assertEqual((self.output / 'foreign').read_text(), 'keep')

    def test_concurrent_empty_destination_is_not_replaced(self):
        original = Path.mkdir
        identity = []
        def mkdir(path, *args, **kwargs):
            if path == self.output:
                original(path)
                identity.append(path.stat().st_ino)
            return original(path, *args, **kwargs)
        with patch.object(Path, 'mkdir', mkdir):
            with self.assertRaises(FileExistsError):
                self.build()
        self.assertEqual(self.output.stat().st_ino, identity[0])
        self.assertEqual(list(self.output.iterdir()), [])
        self.assertEqual(list(self.output.parent.glob('.package-*')), [])

    def test_second_commit_open_failure_is_retryable(self):
        original = Path.open
        calls = []
        def open_file(dest, mode="r", *args, **kwargs):
            if mode != "xb":
                return original(dest, mode, *args, **kwargs)
            calls.append(dest)
            if len(calls) == 2:
                raise OSError('injected')
            return original(dest, mode, *args, **kwargs)
        with patch.object(Path, 'open', open_file):
            with self.assertRaisesRegex(OSError, 'injected'):
                self.build()
        self.assert_retry()

    def test_foreign_replacement_is_preserved_during_rollback(self):
        original = Path.open
        calls = []
        def open_file(dest, mode="r", *args, **kwargs):
            if mode != "xb":
                return original(dest, mode, *args, **kwargs)
            calls.append(dest)
            if len(calls) == 2:
                first = calls[0]
                first.rename(first.with_suffix('.saved'))
                first.write_text('foreign replacement')
                raise OSError('injected')
            return original(dest, mode, *args, **kwargs)
        with patch.object(Path, 'open', open_file):
            with self.assertRaisesRegex(OSError, 'injected'):
                self.build()
        self.assertEqual(calls[0].read_text(), 'foreign replacement')
        self.assertEqual(list(self.output.parent.glob('.package-*')), [])

    def test_partial_copy_failure_is_retryable(self):
        for error in (OSError, KeyboardInterrupt):
            with self.subTest(error=error):
                def fail(source, target):
                    target.write(b'partial')
                    raise error('injected')
                with patch.object(package.shutil, 'copyfileobj', fail):
                    with self.assertRaisesRegex(error, 'injected'):
                        self.build()
                self.assert_retry()
                for p in self.output.iterdir():
                    p.unlink()
                self.output.rmdir()

    def test_replaced_output_directory_is_not_cleaned(self):
        original = Path.open
        calls = []
        def open_file(dest, mode='r', *args, **kwargs):
            if mode == 'xb':
                calls.append(dest)
                if len(calls) == 2:
                    self.output.rename(self.output.with_name('displaced'))
                    self.output.mkdir()
                    (self.output / 'foreign').write_text('keep')
                    raise OSError('injected')
            return original(dest, mode, *args, **kwargs)
        with patch.object(Path, 'open', open_file):
            with self.assertRaisesRegex(OSError, 'injected'):
                self.build()
        self.assertEqual((self.output / 'foreign').read_text(), 'keep')
        self.assertEqual(list(self.output.parent.glob('.package-*')), [])
