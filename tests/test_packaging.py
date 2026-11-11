"""Exercise packaging through its CLI without contacting GitHub or Steam."""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

import test_publisher

ROOT = Path(__file__).resolve().parents[1]


class PackageMetadata(unittest.TestCase):
    def run_package(self, content, output):
        return subprocess.run(
            [sys.executable, str(ROOT / "package.py"), str(content), "AutoMindful", "0.1.1",
             "--out", str(output)], capture_output=True, text=True, timeout=10)

    def test_rejects_vcs_metadata_at_every_depth_before_creating_output(self):
        for metadata in (".git", ".hg", ".svn"):
            for prefix in (Path(), Path("mods/example")):
                for kind in ("directory", "empty-directory", "file"):
                    with self.subTest(metadata=metadata, prefix=prefix, kind=kind), tempfile.TemporaryDirectory() as temporary:
                        root = Path(temporary)
                        content = root / "content"
                        metadata_path = content / prefix / metadata
                        metadata_path.parent.mkdir(parents=True)
                        (content / "ordinary.txt").write_text("valid mod content")
                        if kind != "file":
                            metadata_path.mkdir()
                            if kind == "directory":
                                (metadata_path / "history").write_text("private fixture, not for release")
                        else:
                            metadata_path.write_text("private metadata pointer fixture")
                        output = root / "release"
                        result = self.run_package(content, output)
                        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                        self.assertIn("Select the content folder", result.stderr)
                        self.assertFalse(output.exists(), "rejected content produced release assets")
                        self.assertEqual((content / "ordinary.txt").read_text(), "valid mod content")
                        if kind == "file":
                            self.assertEqual(metadata_path.read_text(), "private metadata pointer fixture")
                        elif kind == "directory":
                            self.assertEqual((metadata_path / "history").read_text(), "private fixture, not for release")
                        else:
                            self.assertEqual(list(metadata_path.iterdir()), [])

    def test_normal_package_and_similar_names_pass_release_validation(self):
        fixture = test_publisher.PublisherCLI()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        content = fixture.root / "content"
        payloads = {
            "mods/AutoMindful/42/mod.info": b"id=AutoMindful\nmodversion=0.1.1\n",
            ".gitignore": b"temporary files\n",
            ".hgignore": b"syntax: glob\n",
            "nested/.svn-notes.txt": b"ordinary documentation\n",
        }
        for name, data in payloads.items():
            path = content / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        output = fixture.root / "release"
        result = self.run_package(content, output)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        archive = output / "AutoMindful-0.1.1.zip"
        manifest = json.loads((output / "manifest.json").read_text())
        expected = {"Contents/" + name: hashlib.sha256(data).hexdigest() for name, data in payloads.items()}
        self.assertEqual(manifest["files"], expected)
        self.assertEqual(manifest["archiveSha256"], hashlib.sha256(archive.read_bytes()).hexdigest())
        with zipfile.ZipFile(archive) as package:
            self.assertEqual(set(package.namelist()), set(expected))
            for name, data in payloads.items():
                self.assertEqual(package.read("Contents/" + name), data)
        for asset in output.iterdir():
            shutil.copyfile(asset, fixture.assets / asset.name)
        fixture.prepare()
        for name, data in payloads.items():
            self.assertEqual((fixture.stage / "Contents" / name).read_bytes(), data)


if __name__ == "__main__":
    unittest.main()
