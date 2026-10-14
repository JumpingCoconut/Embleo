import sys
import json
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import msgpack

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import server


class TrainingMissionTests(unittest.TestCase):
    def test_camp_labels_match_mountain_and_desert_locations(self):
        path = Path(__file__).resolve().parents[1] / "src/offline_responses/api/training-mission/list.json"
        missions = json.loads(path.read_text(encoding="utf-8"))["TrainingMissions"]
        locations = {row["TrainingMissionId"]: row["LocationId"] for row in missions}
        self.assertEqual(locations["exp_mission_005"], "MOC02")
        self.assertEqual(locations["exp_mission_006"], "DEC01")

    def test_camp_scenario_uses_installed_checkpoint_without_changing_template(self):
        template = deepcopy(server.secret_mission_base_scenario)
        checkpoint = dict(_id="CP_camp", _startScenarioNo=7, IsDarkenRestart=0)
        with patch.object(server, "does_file_exist", return_value=False), \
                patch.object(server, "load_json", return_value=dict(Datas=[checkpoint])):
            scenarios = server.fill_scenario_list_from_adapted_scenario("exp_mission_005")
            group = server.fill_scenario_group_from_adapted_scenario("exp_mission_005")
        self.assertEqual(scenarios[0]["ScenarioNo"], 7)
        self.assertEqual(scenarios[0]["ProgressId"], "00007")
        self.assertEqual(group["CheckPoints"][0]["ProgressCheckPointId"], "00007")
        self.assertEqual(group["CheckPoints"][0]["LayoutCheckPointId"], "CP_camp")
        self.assertFalse(group["CheckPoints"][0]["IsDarkenRestart"])
        self.assertEqual(server.secret_mission_base_scenario, template)

    def test_authored_scenario_takes_priority(self):
        authored = [dict(Id="authored")]
        with patch.object(server, "does_file_exist", return_value=True), \
                patch.object(server, "load_json", return_value=authored):
            self.assertIs(server.load_adapted_episode_scenario("exp_mission_005"), authored)

    def test_secret_mission_fallback_is_unchanged(self):
        with patch.object(server, "does_file_exist", return_value=False):
            self.assertIs(server.load_adapted_episode_scenario("pl001_sc001"),
                          server.secret_mission_base_scenario)

    def test_missing_ordinary_scenario_still_fails(self):
        with patch.object(server, "does_file_exist", return_value=False), \
                patch.object(server, "load_json", side_effect=FileNotFoundError):
            with self.assertRaises(FileNotFoundError):
                server.load_adapted_episode_scenario("pl001_ep001")

    def test_camp_requires_one_initial_checkpoint(self):
        for checkpoints in ([], [{}, {}]):
            with self.subTest(checkpoints=checkpoints), \
                    patch.object(server, "does_file_exist", return_value=False), \
                    patch.object(server, "load_json", return_value=dict(Datas=checkpoints)):
                with self.assertRaises(ValueError):
                    server.load_adapted_episode_scenario("exp_mission_005")

    def test_start_preserves_selected_stage_and_saved_character(self):
        selected = dict(CharacterId="pl010", Level=17, Exp=321,
                        VisualEquipment=["saved_costume", "saved_weapon", "", "", "", ""])
        detail = dict(characters=[dict(CharacterId="pl001"), dict(CharacterId="pl010")],
                      userCharacters=[selected], userEquipments=[], baseVisual={})
        original = deepcopy(detail)
        episode = dict(Scenarios=[dict(ScenarioNo=7)], LayoutGroup=dict(CheckPoints=[
            dict(PartyPlayers=["pl001"], LoadPlayers=["pl001"]),
            dict(PartyPlayers=["pl001"], LoadPlayers=[])]))

        def load(path):
            if path.endswith("list.json"):
                return dict(TrainingMissions=[dict(TrainingMissionId="exp_mission_005",
                                                  LocationId="MOC02")])
            return {}

        with server.app.test_request_context("/api/training-mission/start", method="POST",
                data=msgpack.packb(dict(trainingMissionId="exp_mission_005", characterId="pl010"))), \
                patch.object(server, "load_json", side_effect=load), \
                patch.object(server, "fill_episode_character_detail", return_value=deepcopy(detail)), \
                patch.object(server, "fill_episode_detail_by_episode_id", return_value=episode), \
                patch.object(server, "fill_episode_master_group", return_value={}):
            result = msgpack.unpackb(server.level_up_camp_start(), raw=False)

        self.assertEqual(result["CharacterDetail"]["characters"], [dict(CharacterId="pl010")])
        visual = result["CharacterDetail"]["baseVisual"]
        self.assertEqual(visual["characters"][0]["VisualEquipment"], selected["VisualEquipment"])
        self.assertEqual(visual["settings"][0]["ScenarioNo"], 7)
        self.assertEqual(visual["settings"][0]["Ids"], [visual["characters"][0]["VisualId"]])
        for checkpoint in result["EpisodeDetail"]["LayoutGroup"]["CheckPoints"]:
            self.assertEqual(checkpoint["PartyPlayers"], ["pl010"])
            self.assertEqual(checkpoint["LoadPlayers"], ["pl010"])
        self.assertEqual(result["EpisodeDetailUser"]["startScenarioNo"], 7)
        self.assertEqual(result["EpisodeDetailUser"]["playCharacters"][0],
                         dict(characterId="pl010", hp=240, sp=45, level=17, exp=321))
        self.assertEqual(result["MissionDetail"]["TrainingMissionId"], "exp_mission_005")
        self.assertEqual(result["MissionDetail"]["LocationId"], "MOC02")
        self.assertEqual(result["MissionDetail"]["Detail"]["Finishes"], [
            dict(Type=1, Flag=1, Option=""),
            dict(Type=3, Flag=0, Option=""),
            dict(Type=2, Flag=1, Option="")])
        self.assertEqual(detail, original)


if __name__ == "__main__":
    unittest.main()
