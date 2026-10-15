from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import setup_server


class SetupPathTests(unittest.TestCase):
    def test_debug_config_disables_setup_stages_without_changing_defaults(self):
        path = Path(setup_server.__file__)
        source = path.read_text(encoding="utf-8")
        stages = ("manifest", "download", "extract", "adapt_master_data", "adapt_scenario", "generate")
        for debug in (False, True):
            with self.subTest(debug=debug):
                namespace = {"__file__": str(path), "__name__": "setup_debug_test"}
                configured = source.replace("DEBUG_CONFIG = False", "DEBUG_CONFIG = " + str(debug))
                exec(compile(configured, str(path), "exec"), namespace)
                for stage in stages:
                    self.assertEqual(namespace[stage], not debug)

    def test_setup_data_paths_follow_module_in_both_layouts(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "src" / "setup_server.py").read_text(encoding="utf-8")
        for folder in (root / "src", root / "runtime"):
            with self.subTest(folder=folder):
                namespace = {"__file__": str(folder / "setup_server.py"),
                             "__name__": "setup_path_test"}
                exec(compile(source, namespace["__file__"], "exec"), namespace)
                self.assertEqual(namespace["DATA_FOLDER"], folder / "data")
                self.assertEqual(namespace["EXTRACT_FOLDER"], folder / "data" / "extract")
                self.assertEqual(namespace["asset_server_link_file"], folder / "asset_server_link.txt")
                self.assertEqual(namespace["extract_file"].__defaults__[0],
                                 folder / "data" / "extract")

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
