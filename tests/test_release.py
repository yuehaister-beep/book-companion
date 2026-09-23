import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import zipfile
import hashlib

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("build_release", ROOT / "tools/build_release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def test_archive_allowlist_and_checksums(self):
        target = self.folder / "release"
        sums = release.build(ROOT, target)
        for name, checksum in sums.items():
            self.assertEqual(checksum, hashlib.sha256((target / name).read_bytes()).hexdigest())
            with zipfile.ZipFile(target / name) as bundle:
                manifest = json.loads(bundle.read("SHA256SUMS.json"))
                self.assertEqual(set(bundle.namelist()), set(manifest) | {"SHA256SUMS.json"})
                for path, value in manifest.items():
                    self.assertNotIn("..", Path(path).parts)
                    self.assertEqual(value, hashlib.sha256(bundle.read(path)).hexdigest())

    def test_output_not_overwritten(self):
        target = self.folder / "existing"
        target.mkdir()
        with self.assertRaises(FileExistsError):
            release.build(ROOT, target)

    def test_source_directory_not_used_for_output(self):
        with self.assertRaises(ValueError):
            release.build(ROOT, ROOT / "release")

    def test_unknown_files_not_collected(self):
        fixture = self.folder / "source"
        for name in release.FILES:
            target = fixture / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
        (fixture / "private-manuscript.txt").write_text("PRIVATE FIXTURE NOT FOR RELEASE")
        self.assertNotIn("private-manuscript.txt", release.collect(fixture))

    def test_symlink_rejected(self):
        fixture = self.folder / "source"
        fixture.mkdir()
        (fixture / ".gitignore").symlink_to(ROOT / ".gitignore")
        with self.assertRaises(ValueError):
            release.collect(fixture)

    def test_private_pattern_rejected_without_printing_value(self):
        fixture = self.folder / "source"
        fixture.mkdir()
        private = "sk-" + "x" * 30
        (fixture / ".gitignore").write_text(private)
        with self.assertRaises(ValueError) as result:
            release.collect(fixture)
        self.assertNotIn(private, str(result.exception))


if __name__ == "__main__":
    unittest.main()
