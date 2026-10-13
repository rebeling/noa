import json
import os
import subprocess
import sys
import unittest

HEAVY_MODULES = (
    "anthropic",
    "kokoro_onnx",
    "openai",
    "parakeet_mlx",
    "piper",
    "pysilero_vad",
)


class StartupImportTests(unittest.TestCase):
    def test_app_import_skips_feature_model_modules(self):
        probe = (
            "import json, sys\n"
            "import app.main\n"
            f"modules = {HEAVY_MODULES!r}\n"
            "print(json.dumps([name for name in modules if name in sys.modules]))\n"
        )
        env = os.environ.copy()
        env["SECRET_KEY"] = "startup-import-test-secret-key-with-enough-entropy"

        result = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            check=False,
            env=env,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [])


if __name__ == "__main__":
    unittest.main()
