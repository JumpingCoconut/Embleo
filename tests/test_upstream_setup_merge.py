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
            with patch('builtins.open', side_effect=AssertionError('Disabled setup must not access data')):
                setup_server.setup('')

    def test_setup_keeps_sequences_from_integrated_master_data_pipeline(self):
        from scripts.adapt.master_data.sequence import adapt_debug_sequences_master_data
        from scripts.adapt import adapt_sequence_data as recovery

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            extracted = root / 'extract'
            downloaded = root / 'download'
            output = root / 'masterdata'
            extracted.mkdir()
            output.mkdir()
            (downloaded / 'characters/enemy').mkdir(parents=True)
            source = extracted / 'SequenceMasterDataObject.json'
            attack = {'id': 'em0001_001', 'sequenceName': 'Attack1',
                      'clipDatas': [{'damage': 5}]}
            source.write_text(json.dumps({
                'attackList': [{'AttackSetting': [attack]}],
                'moveList': [], 'updateParameterList': [],
            }), encoding='utf-8')
            recovered = [{'EnemyId': 'em0001_001', 'Category': 'MoveSetting',
                          'Data': json.dumps({'MoveSetting': [
                              {'sequenceName': 'Walk010', 'speed': [0.8]}]})}]

            def adapt_masters(extract_folder, output_folder):
                self.assertEqual(extract_folder, extracted)
                adapt_debug_sequences_master_data(source, output_folder, downloaded)

            with patch.multiple(setup_server, manifest=False, download=False, extract=False,
                                adapt_master_data=True, adapt_scenario=False, generate=False,
                                EXTRACT_FOLDER=extracted, DOWNLOAD_FOLDER=downloaded,
                                MASTER_DATA_FOLDER=output), \
                    patch.object(setup_server, 'adapt_debug_master_data', side_effect=adapt_masters), \
                    patch.object(setup_server, 'generate_character_chronology_json'), \
                    patch.object(setup_server, 'extract_all_SequenceSetting_files', create=True,
                                 side_effect=AssertionError('Sequence recovery belongs inside master adaptation')), \
                    patch.object(setup_server, 'adapt_sequence_data_from_animation_data', create=True,
                                 side_effect=AssertionError('Do not overwrite combined combat masters')), \
                    patch('scripts.adapt.master_data.sequence.recover_special_skills', return_value=[]), \
                    patch('scripts.adapt.master_data.sequence.recover_minion_commands', return_value=[]), \
                    patch.object(recovery, 'extract_all_SequenceSetting_files') as extract_settings, \
                    patch.object(recovery, 'adapt_sequence_data_from_animation_data',
                                 return_value=([], recovered)) as adapt_sequences:
                setup_server.setup('')

            extract_settings.assert_called_once()
            adapt_sequences.assert_called_once()
            rows = json.loads((output / 'EnemySequenceMasterData.json').read_text())
            self.assertEqual({row['Category'] for row in rows}, {'AttackSetting', 'MoveSetting'})
            attacks = next(row for row in rows if row['Category'] == 'AttackSetting')
            self.assertEqual(json.loads(attacks['Data'])['AttackSetting'], [attack])


if __name__ == '__main__':
    unittest.main()
