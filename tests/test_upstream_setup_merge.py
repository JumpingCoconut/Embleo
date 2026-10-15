import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from scripts.adapt.episode_data.items import adapt_items_for_episode_layout
from scripts.generate import generate_save_file as saves
import setup_server


class UpstreamSetupMergeTests(unittest.TestCase):
    def test_equipment_defaults_resolve_server_data_independently_of_cwd(self):
        expected = Path(saves.__file__).resolve().parents[2] / 'data/masterdata/EquipmentMasterData.json'
        with tempfile.TemporaryDirectory() as directory:
            previous = os.getcwd()
            try:
                os.chdir(directory)
                with patch.object(saves, 'load_json', return_value=[
                    {'EquipmentId': 'merge-fixture', 'Category': 2}
                ]) as load:
                    equipment = saves.generateUserEquipment(True)
                load.assert_called_once_with(expected)
                self.assertTrue(any(row['EquipmentId'] == 'merge-fixture' for row in equipment))
            finally:
                os.chdir(previous)

    def test_upstream_item_folder_accepts_path_without_trailing_separator(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'EpisodeBreakableMasterDataObject.json').write_text(json.dumps({'Datas': [{
                '_id': 'box', '_masterID': 'resource', '_stackNum': 2,
                '_parallelNum': 1, '_startScenarioNo': 3, '_endScenarioNo': 9
            }]}), encoding='utf-8')
            rows = adapt_items_for_episode_layout(root)
            self.assertEqual(len(rows), 1)
            self.assertEqual((rows[0]['EpisodeItemId'], rows[0]['ItemDropMethod']), ('box', 2))

    def test_setup_uses_absolute_destination(self):
        with patch.multiple(setup_server, manifest=False, download=False, extract=False,
                            adapt_master_data=False, adapt_scenario=False, generate=False):
            setup_server.setup('')


if __name__ == '__main__':
    unittest.main()
