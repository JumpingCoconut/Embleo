import UnityPy
import json
from pathlib import Path


action_script_path_number = 5650615754327761616


def group_objects_by_container_path(unitypy_env):
    container_groups = {}

    for path, obj in unitypy_env.container.items():

        if path not in container_groups:
            container_groups[path] = []

        container_groups[path].append(obj)

    return container_groups


def group_objects_by_path_id(object_list):
    grouped_objects = {}

    for obj in object_list:
        path_id = obj.m_PathID

        grouped_objects[str(path_id)] = obj

    return grouped_objects


def get_object_by_script_path_id(object_list, path_number):
    for file in object_list:
        parsed_object = file.deref_parse_as_dict()
        script_path_id = parsed_object["m_Script"]["m_PathID"]

        if script_path_id == path_number:
            return parsed_object


def deref_tracks(tracks, path_id_objects):
    parsed_tracks = []

    for track in tracks:
        parsed_track = {
            "behaviour": {},
            "clips": [],
            "keys": []
        }

        # Parse track
        parsed_track["behaviour"] = path_id_objects[str(track["behaviourPrefab"]["m_PathID"])].deref_parse_as_dict()

        for clip in track["clips"]:
            parsed_clip = {
                "behaviour": path_id_objects[str(clip["behaviourPrefab"]["m_PathID"])].deref_parse_as_dict()
            }

            parsed_track["clips"].append(parsed_clip)

        parsed_track["keys"] = track["keys"]

        parsed_tracks.append(parsed_track)

    return parsed_tracks


def extract_ActionData(animation_data, sequence_setting):
    container_base = "assets/variableresources/core/assetbundles/"

    container_path = container_base + sequence_setting["basePath"].lower()

    # Action containers, some enemies have the same action names in multiple container paths
    action_containers = set(
        container_path + action_name.lower() + ".asset" for action_name in sequence_setting["sequenceNames"]
    )

    container_groups = group_objects_by_container_path(animation_data)

    actions = []

    # Get action description files, that has same name as sequenceName
    for path in action_containers:

        if path not in container_groups:
            print("This asset is not in the animation", path)
            continue

        action_files = container_groups[path]

        # Find action description
        action_overview = get_object_by_script_path_id(action_files, action_script_path_number)

        # Group files by m_PathID
        path_id_objects = group_objects_by_path_id(action_files)

        # Get all objects, referenced by action_objects
        deref_action_overview = {
            "owner_id": sequence_setting["owner_id"],
            "action_name": action_overview["m_Name"],
            "tracks": []
        }

        # print(action_overview)

        deref_action_overview["tracks"] = deref_tracks(action_overview["tracks"], path_id_objects)

        actions.append(deref_action_overview)

    return actions


def convert_move_track_to_move_data(move_track, action_name, owner_id):
    MoveSetting = {
        "id": owner_id,
        "sequenceName": action_name,
        "totalMoveCount": 0,
        "moveCount": [],
        "direction": [],
        "speed": []
    }

    # print(action["action_name"])

    clip_counter = 0
    for clip in move_track["clips"]:
        # print(clip)

        if clip["behaviour"]["m_Name"] == "EnemyMove Clip":
            MoveSetting["totalMoveCount"] += 1
            MoveSetting["moveCount"].append(clip_counter)
            MoveSetting["direction"].append(clip["behaviour"]["direction"])
            MoveSetting["speed"].append(clip["behaviour"]["speed"])

            clip_counter += 1

    return MoveSetting


def convert_attack_track_to_attack_data(move_track, action_name, owner_id):
    AttackSetting = {
        "id": owner_id,
        "sequenceName": action_name,
        "baseInfo": None,
        "totalClipCount": 0,
        "clipCount": [],
        "clipDatas": []
    }

    AttackSetting["baseInfo"] = {
        "ChargeType": 0,
        "IsInvincible": 0,
        "IsSuperArmor": 0,
        "IsArmor": 0,
        "IsStrongAttack": 0,
        "IsFloating": 0,
        "IsForceDamageAction": 0,
        "SearchDistance": 0.0,
        "ValidSearchLayerDistance": -1.0,
        "OffsetFront": 0.0,
        "OffsetSide": 0.0,
        "OffsetRear": 0.0,
        "PriorityType": 0,
        "PriorityFlag": 0,
        "ServiceFlags": 0,
        "NoSetTarget": 0,
        "DamageCutRate": 0.0,
        "MultiTargetKey": "",
        "IsForceMultiTarget": 0,
        "KeepExistTarget": 0,
        "BuffKey": "",
        "ActionUniqueKey": "",
        "IsWeakInvincible": 0
    }

    clip_counter = 0
    for clip in move_track["clips"]:
        # print(clip)

        clip_data = {
        }

        # print()
        if clip["behaviour"]["m_Name"] in ["Attack Clip", "EnemyAttack Clip"]:
            AttackSetting["totalClipCount"] += 1

            if "_hitParameter" in clip["behaviour"]:
                clip_data["enemy_Hit"] = clip["behaviour"]["_hitParameter"]

            if "attackClipSettings" in clip["behaviour"]:
                clip_data["hitSetting"] = clip["behaviour"]["hitSettings"]

            if clip_data == {}:
                print("Unknown enemy attack clip")

            clip_counter += 1

    return AttackSetting


def convert_enemy_action_data_to_sequence_data(actions, owner_id):
    AttackSetting = []
    MoveSetting = []

    for action in actions:
        action_name = action["action_name"]
        print("Action Name", action_name)

        for track in action["tracks"]:

            track_behaviour_name = track["behaviour"]["m_Name"]

            if track_behaviour_name == "Attack Track":
                attack_setting = convert_attack_track_to_attack_data(track, action_name, owner_id)

                if attack_setting["totalClipCount"] > 0:
                    AttackSetting.append(attack_setting)

            elif track_behaviour_name == "Move Track":
                move_setting = convert_move_track_to_move_data(track, action_name, owner_id)

                if move_setting["totalMoveCount"] > 0:
                    MoveSetting.append(move_setting)

    return AttackSetting, MoveSetting


def adapt_enemy_sequence(extracted_setting_folder, animation_folder):
    sequence_master_data = []

    enemy_animation_files = sorted(Path(animation_folder).rglob("*.ab"))

    # Enemy animation files have all sequences for an enemy group
    for animation_asset_bundle_path in enemy_animation_files:
        animation_asset_bundle_path = str(animation_asset_bundle_path)

        animation_data = UnityPy.load(animation_asset_bundle_path)

        # Load correct SequenceSetting file
        # ../em0001_slgdjg.ab -> em0001
        enemy_group_name = animation_asset_bundle_path[len(str(animation_folder)) + 1:
                                                       animation_asset_bundle_path.rfind("_")]
        sequence_file_path = extracted_setting_folder / (enemy_group_name + ".json")

        enemy_group_sequence_data: json

        with open(sequence_file_path, "r", encoding="UTF-8") as f:
            enemy_group_sequence_data = json.load(f)

        # Extract and adapt action data
        for owner_id, sequence_setting in enemy_group_sequence_data.items():

            # Action data has all sequence parameters
            action_data = extract_ActionData(animation_data, sequence_setting)

            print("Owner ID", owner_id)

            attack_data, move_data = convert_enemy_action_data_to_sequence_data(action_data, owner_id)

            attack_setting = {
                "EnemyId": owner_id,
                "Category": "AttackSetting",
                "Data": json.dumps({"AttackSetting": attack_data})
            }

            move_setting = {
                "EnemyId": owner_id,
                "Category": "MoveSetting",
                "Data": json.dumps({"MoveSetting": move_data})
            }

            sequence_master_data.append(attack_setting)
            sequence_master_data.append(move_setting)

    return sequence_master_data
