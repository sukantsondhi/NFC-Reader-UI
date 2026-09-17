from contextlib import redirect_stdout
import io
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from nfc_workbench.__main__ import VERSION
from tools import check_repository


ROOT = Path(__file__).resolve().parents[1]


class RepositoryTests(unittest.TestCase):
    def test_both_source_launchers_resolve(self):
        for arguments in (("app.py", "--version"), ("-m", "nfc_workbench", "--version")):
            with self.subTest(arguments=arguments):
                result = subprocess.run([sys.executable, *arguments], cwd=ROOT,
                                        capture_output=True, text=True, check=True, timeout=30)
                self.assertEqual(result.stdout.strip(), VERSION)

    def test_application_and_packaging_paths(self):
        from nfc_workbench.ui import ASSETS, ROOT as resource_root

        self.assertEqual(resource_root, ROOT)
        self.assertEqual(ASSETS, ROOT / "nfc_workbench" / "assets")
        self.assertTrue((ASSETS / "theme.qss").is_file())
        specification = ROOT / "packaging" / "windows" / "NFCWorkbench.spec"
        self.assertTrue(specification.is_file())
        build_requirements = specification.parent / "requirements-build.txt"
        included = build_requirements.read_text(encoding="utf-8").splitlines()[0].removeprefix("-r ")
        self.assertEqual((build_requirements.parent / included).resolve(), ROOT / "requirements.txt")
        self.assertEqual(sorted(path.name for path in ROOT.glob("*.py")), ["app.py"])

    def test_audit_handles_moves_and_rejects_tracked_junk(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text("# Example\n", encoding="utf-8")
            (root / "unused.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
            generated = root / "build" / "report.json"
            generated.parent.mkdir()
            generated.write_text("{}", encoding="utf-8")
            with patch.object(check_repository, "ROOT", root):
                with patch.object(check_repository.subprocess, "check_output", return_value=b"README.md\0old-moved-file.py\0"):
                    with redirect_stdout(io.StringIO()):
                        self.assertEqual(check_repository.main(), 0)
                with patch.object(check_repository.subprocess, "check_output", return_value=b"README.md\0unused.svg\0build/report.json\0"):
                    report = io.StringIO()
                    with redirect_stdout(report):
                        self.assertEqual(check_repository.main(), 1)
                    self.assertIn("Unreferenced image", report.getvalue())
                    self.assertIn("Generated/environment file", report.getvalue())


if __name__ == "__main__":
    unittest.main()