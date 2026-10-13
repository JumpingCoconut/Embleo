import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from copy import deepcopy

import msgpack

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from training_mission import checkpoint_scenario, mission_token, token_character
from flask import g
import server


class TrainingMissionTests(unittest.TestCase):
    def test_token_rejects_tampering_another_account_and_another_stage(self):
        token = mission_token('account-a', 'exp_mission_005', 'pl008')
        self.assertEqual(token_character(token, 'account-a', 'exp_mission_005'), 'pl008')
        for value, account, mission in ((token + 'x', 'account-a', 'exp_mission_005'),
                (token, 'account-b', 'exp_mission_005'),
                (token, 'account-a', 'exp_mission_001')):
            with self.assertRaises(ValueError):
                token_character(value, account, mission)

    def test_bootstrap_uses_installed_checkpoint_identity_and_range(self):
        rows = [dict(_id='CP_native', _startScenarioNo=7, IsDarkenRestart=0)]
        original = deepcopy(rows)
        result = checkpoint_scenario(rows)
        self.assertEqual(result[0]['ScenarioNo'], 7)
        self.assertEqual(result[0]['Progress']['LayoutCheckPointId'], 'CP_native')
        self.assertEqual(result[0]['Progress']['ProgressCheckPointId'], result[0]['Id'])
        self.assertEqual(rows, original)

    def test_missing_ordinary_scenario_is_not_replaced(self):
        with patch.object(server, 'does_file_exist', return_value=False), \
                patch.object(server, 'load_json', side_effect=FileNotFoundError):
            with self.assertRaises(FileNotFoundError):
                server.load_adapted_episode_scenario('pl001_ep001')

    def test_authored_camp_scenario_takes_priority(self):
        authored = [dict(Id='native')]
        with patch.object(server, 'does_file_exist', return_value=True), \
                patch.object(server, 'load_json', return_value=authored):
            self.assertIs(server.load_adapted_episode_scenario('exp_mission_005'), authored)

    def test_start_preserves_selected_stage_character_equipment_and_saved_level(self):
        selected = dict(CharacterId='pl008', Level=17, Exp=321,
                        VisualEquipment=['costume', 'weapon', '', '', '', ''])
        characters = [selected]
        detail = dict(userCharacters=characters, userEquipments=[], baseVisual={})
        episode = dict(Scenarios=[dict(ScenarioNo=1)], LayoutGroup=dict(CheckPoints=[
            dict(PartyPlayers=['pl001'], LoadPlayers=[])]))
        original = deepcopy(detail)
        calculator = Mock()
        calculator.character.return_value = dict(Hp=9876)
        def load(path):
            if path.endswith('list.json'):
                return dict(TrainingMissions=[dict(TrainingMissionId='exp_mission_005',
                                                 LocationId='SCH01')])
            return {}
        with server.app.test_request_context('/api/training-mission/start', method='POST',
                data=msgpack.packb(dict(trainingMissionId='exp_mission_005', characterId='pl008'))), \
                patch.object(server, 'load_json', side_effect=load), \
                patch.object(server, 'fill_episode_character_detail', return_value=deepcopy(detail)), \
                patch.object(server, 'fill_episode_detail_by_episode_id', return_value=episode), \
                patch.object(server, 'fill_episode_master_group', return_value={}), \
                patch.object(server, 'installed_calculator', return_value=calculator):
            g.account_id = "test-account"
            result = msgpack.unpackb(server.level_up_camp_start(), raw=False)
        self.assertEqual(result['MissionDetail']['TrainingMissionId'], 'exp_mission_005')
        self.assertEqual(result['MissionDetail']['LocationId'], 'SCH01')
        self.assertEqual(result['EpisodeDetail']['LayoutGroup']['CheckPoints'][0]['PartyPlayers'], ['pl008'])
        self.assertEqual(result['CharacterDetail']['baseVisual']['characters'][0]['VisualEquipment'],
                         selected['VisualEquipment'])
        self.assertEqual(result['EpisodeDetailUser']['playCharacters'][0],
                         dict(characterId='pl008', hp=9876, sp=0, level=17, exp=321))
        self.assertEqual(detail, original)

    def test_finish_returns_existing_state_without_granting_experience(self):
        characters = [dict(CharacterId='pl008', Level=17, Exp=321)]
        def load(path):
            if path.endswith('list.json'):
                return dict(TrainingMissions=[dict(TrainingMissionId='exp_mission_005')])
            if path.endswith('UserCharacter.json'):
                return deepcopy(characters)
            return {}
        with server.app.test_request_context('/api/training-mission/retire', method='POST',
                data=msgpack.packb(dict(trainingMissionId='exp_mission_005',
                                       missionToken=mission_token('test-account', 'exp_mission_005', 'pl008')))), \
                patch.object(server, 'load_json', side_effect=load), \
                patch.object(server, 'reward_result', return_value={}):
            g.account_id = "test-account"
            result = msgpack.unpackb(server.level_up_camp_finish(), raw=False)
        self.assertEqual(result['CharacterId'], 'pl008')
        self.assertEqual(result['AddExp'], 0)
        self.assertEqual(result['Result']['Characters'], characters)


if __name__ == '__main__':
    unittest.main()
