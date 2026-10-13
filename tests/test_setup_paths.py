from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import setup_server


class SetupPathTests(unittest.TestCase):
    def test_news_path_follows_setup_module_in_both_layouts(self):
        root = Path(__file__).resolve().parents[1]
        settings = {"enabled": False}
        for module_path in (root / "src" / "setup_server.py",
                            root / "runtime" / "setup_server.py"):
            with self.subTest(module_path=module_path), patch.multiple(
                setup_server, manifest=False, download=False, extract=False,
                adapt_master_data=False, adapt_scenario=False, generate=False,
                __file__=str(module_path),
            ), patch.object(setup_server, "generate_server_news") as news:
                setup_server.setup("https://example.invalid/", settings)
                news.assert_called_once_with(
                    settings, path=module_path.parent / "offline_responses"
                    / "api" / "news" / "list.json",
                )


if __name__ == "__main__":
    unittest.main()
