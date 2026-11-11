import os
import subprocess
import sys
import unittest
from pathlib import Path


class PDFExportIntegrationTests(unittest.TestCase):
    def test_pdf_export_with_real_qt_font_backend(self):
        root = Path(__file__).resolve().parent.parent
        environment = os.environ.copy()
        if os.name == "nt":
            environment["QT_QPA_PLATFORM"] = "windows"
        environment["PYTHONPATH"] = os.pathsep.join(
            (str(root), environment.get("PYTHONPATH", ""))
        )
        result = subprocess.run(
            [sys.executable, str(root / "tests" / "pdf_test_worker.py"), "-v"],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
