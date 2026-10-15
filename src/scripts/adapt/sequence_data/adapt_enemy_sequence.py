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


def extract_track_data(animation_data, sequence_setting):
    container_base = "assets/variableresources/core/assetbundles/"

    container_path = container_base + sequence_setting["basePath"].lower()

    # Action containers, some enemies have the same action names in multiple container paths
    sequence_containers = set(
        container_path + action_name.lower() + ".asset" for action_name in sequence_setting["sequenceNames"]
    )

    container_groups = group_objects_by_container_path(animation_data)

    actions = []

    # Get action description files, that has same name as sequenceName
    for path in sequence_containers:

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


ATTACK_CLIPS = {
    # Player attacks
    'Attack Clip': ('clip_Attack', 'attackClipSettings'),
    'GunAttack Clip': ('clip_Gun', 'gunAttackClipSettings'),
    'DeathBall Clip': ('clip_DeathBall', 'gunAttackClipSettings'),
    'Summon Clip': ('clip_Summon', 'clipSettings'),
    'LaserAttack Clip': ('clip_Laser', 'clipSettings'),
    'ThrowWeapon Clip': ('clip_ThrowWeapon', 'gunAttackClipSettings'),
    'HomingGun Clip': ('clip_HomingGun', 'gunAttackClipSettings'),
    'Charging Clip': ('clip_Charging', 'ChargingClipSettings'),
    'GrenadeAttack Clip': ('clip_Grenade', 'gunAttackClipSettings'),
    'PutShooting Clip': ('clip_PutShoot', 'gunAttackClipSettings'),
    'LookTargetGunAttack Clip': ('clip_LookGun', 'gunAttackClipSettings'),
    'Grenade PlungingFireAttack Clip': ('clip_Plunging', 'gunAttackClipSettings'),

    'MinionOrder Clip': ('clip_MinionOrder', 'minionOrderSettings'),
    'MinionAttack Clip': ('clip_MinionAttack', 'minionAttackClipSettings'),
    'RegisterBuff Clip': ('clip_RegisterBuff', 'clipSettings'),
    'AreaGuard Clip': ('clip_AreaGuard', 'clipSettings'),

    # Enemy Attacks
    'EnemyAttack Clip': ('enemy_Hit', '_hitParameter'),
    'EnemyColliderAttack Clip': ('enemy_ColliderHit', '_hitParameter'),
    'EnemyThrowGrabAttack Clip': ('enemy_Throw', '_grabParameter'),
    # LinkThrow?
    'EnemyLaserAttack Clip': ('enemy_Laser', '_laserParameter'),
    'EnemyCatchAttack Clip': ('enemy_CatchAttack', 'm_catchParam'),

    # Are EnemyHeal and EnemyRevive Clip suppose to be handled here?
    # em0111_01 and em0111_02 (Phoenix raid boss)
}

ATTACK_CLIPS_SKIP = {
    "RepairGauge Clip",
    "RevertWeapon Clip",  # Has no values at all
    "SkillActiveCharge Clip",  # August's Charge5, unrelated
    "ChargingRate By RemainGauge Clip",  # Lucien Charge5, unrelated
    "ResetCharge Clip",  # Celia Charge1, no values

    # Maxime, not meant to be parsed by this script
    "ResetTimeDecrease Clip",
    "TimeDecrease Clip",
    "Clear TimeDecrease EmptyTarget Clip",
    "BattleActionUI Clip",
    "BattleActionUI CheckTimeDecrease Clip",
    "PlayStateByTimeDecreaseParam Clip",

    # Lydie, not meant to be parsed by this script
    "InputChargeGauge Clip",
    "Setup InputChargeGauge Clip",
    "Reset InputChargeGauge Clip",
    "PlayStateByChargeParam Clip",

    # Charles
    "CreateMinionBit Clip",
    "MinionUnleash Clip",

    "EnemyHeal Clip",
    "EnemyRevive Clip"
}


def convert_attack_track_to_attack_data(attack_track, sequence_name, owner_id):
    AttackSetting = {
        "id": owner_id,
        "sequenceName": sequence_name,
        "baseInfo": None,
        "totalClipCount": 0,
        "clipCount": [],
        "clipDatas": []
    }

    clip_counter = 0
    for clip in attack_track["clips"]:
        clip_MonoBehaviour = clip["behaviour"]
        clip_m_Name = clip_MonoBehaviour["m_Name"]
        # print(clip)

        # print()
        if clip_m_Name in ATTACK_CLIPS:
            destination_key, source_key = ATTACK_CLIPS[clip_m_Name]

            attack_clip_setting = {
                "hitSetting": clip_MonoBehaviour.get("hitSettings", None),
                destination_key: clip_MonoBehaviour[source_key]
            }

            if clip_m_Name == "MinionAttack Clip":
                attack_clip_setting["clip_Attack"] = clip_MonoBehaviour["attackClipSettings"]

            if clip_m_Name == "EnemyThrowGrabAttack Clip":
                print(clip_MonoBehaviour.keys())

                if "_throwAttackParameter" in clip_MonoBehaviour:
                    attack_clip_setting["enemy_Throw"] = clip_MonoBehaviour["_throwAttackParameter"]

            AttackSetting["totalClipCount"] += 1
            AttackSetting["clipDatas"].append(attack_clip_setting)

            clip_counter += 1
        elif clip_m_Name not in ATTACK_CLIPS_SKIP:
            print(owner_id, sequence_name, "-", clip_m_Name, "-", "Unknown attack clip")

    return AttackSetting


MOVE_CLIPS = [
    "Move Clip",
    "DodgingMove Clip",
    "EnemyMove Clip"
]


def convert_move_track_to_move_data(move_track, sequence_name, owner_id):
    MoveSetting = {
        "id": owner_id,
        "sequenceName": sequence_name,
        "totalMoveCount": 0,
        "moveCount": [],
        "direction": [],
        "speed": []
    }

    # print(action["action_name"])

    clip_counter = 0
    for clip in move_track["clips"]:
        # print(clip)

        if clip["behaviour"]["m_Name"] in MOVE_CLIPS:
            MoveSetting["totalMoveCount"] += 1
            MoveSetting["moveCount"].append(clip_counter)
            MoveSetting["direction"].append(clip["behaviour"]["direction"])
            MoveSetting["speed"].append(clip["behaviour"]["speed"])

            clip_counter += 1

    return MoveSetting


def adapt_update_parameter_track(track, sequence_name, owner_id):
    UpdateParameterSetting = {
        "id": owner_id,
        "sequenceName": sequence_name,
        "totalClipCount": 0,
        "clipCount": [],
        "clipDatas": []
    }

    # print(action["action_name"])

    for clip in track["clips"]:
        # print(clip)

        if clip["behaviour"]["m_Name"] in MOVE_CLIPS:
            UpdateParameterSetting["totalMoveCount"] += 1

    return UpdateParameterSetting


def adapt_action(action, owner_id):
    attack_setting = {}
    move_setting = {}
    update_setting = {}

    action_name = action["action_name"]
    # print("Action Name", action_name)

    base_attack_info = {}

    for track in action["tracks"]:

        track_behaviour_name = track["behaviour"]["m_Name"]

        if track_behaviour_name == "Animator Track":
            clip_count = len(track["clips"])
            if clip_count > 1:
                pass
                # print(owner_id, action_name, "has Animator Track with {} clips".format(clip_count))

            for clip in track["clips"]:
                if clip.get("isAttack"):
                    base_attack_info = clip["attackBaseInfo"]

        elif track_behaviour_name == "Attack Track":
            attack_setting = convert_attack_track_to_attack_data(track, action_name, owner_id)

        elif track_behaviour_name == "Move Track":
            move_setting = convert_move_track_to_move_data(track, action_name, owner_id)

    if base_attack_info != {}:
        attack_setting["baseInfo"] = base_attack_info

    return attack_setting, move_setting, update_setting


def adapt_character_sequences(extracted_setting_folder, character_player_folder):
    sequence_master_data = []

    sequence_setting_files = Path(extracted_setting_folder).rglob("*.json")

    for sequence_setting_path in sequence_setting_files:
        sequence_setting: json

        with open(sequence_setting_path, "r", encoding="UTF-8") as f:
            sequence_setting = json.load(f)

        character_id = sequence_setting["owner_id"]
        # print("Character ID", character_id)

        # Character's sequences
        character_sequence_folder = character_player_folder / character_id / "sequences"

        sequence_file_by_sequence_name = {}
        sequence_file_path_list = Path(character_sequence_folder).rglob("*.ab")
        for asset_bundle_path in sequence_file_path_list:
            file_name = asset_bundle_path.name
            file_action_name = file_name[:file_name.rfind("_")]

            sequence_file_by_sequence_name[file_action_name] = asset_bundle_path

        attacks = []
        moves = []
        updates = []

        for sequence_name in sequence_setting["sequenceNames"]:
            asset_bundle_path = sequence_file_by_sequence_name[sequence_name.lower()]
            # print(sequence_name, asset_bundle_path)

            sequence_bundle_data = UnityPy.load(str(asset_bundle_path))

            single_sequence_setting = sequence_setting
            single_sequence_setting["sequenceNames"] = [sequence_name]

            action_data = extract_track_data(sequence_bundle_data, sequence_setting)
            # print(action_data)

            for action in action_data:
                attack_data, move_data, update_data = adapt_action(action, character_id)
                # attack_data, move_data = convert_enemy_action_data_to_sequence_data(action_data, character_id)

                if attack_data != {}:
                    attacks.append(attack_data)

                if move_data != {}:
                    moves.append(move_data)

                if update_data != {}:
                    updates.append(update_data)

        # Character's Mystic Artes
        character_special_skill_folder = character_player_folder / character_id / "specialskill"
        special_skill_bundle_path_list = Path(character_special_skill_folder).rglob("*/specialskill@*.ab")

        special_skill_base_path = "characters/player/{char_id}/specialskill/{skill_folder_name}/"

        for special_skill_bundle_path in special_skill_bundle_path_list:
            special_skill_bundle_data = UnityPy.load(str(special_skill_bundle_path))

            skill_file_name = special_skill_bundle_path.name
            skill_name = skill_file_name[:skill_file_name.rfind("_")]
            skill_folder_name = special_skill_bundle_path.parent.name
            print(skill_folder_name)


            special_skill_sequence_setting = {
                "owner_id": character_id,
                "basePath": special_skill_base_path.format(char_id=character_id, skill_folder_name=skill_folder_name),
                "sequenceNames": [
                    "SpecialSkill@" + str(skill_folder_name)
                ]
            }

            print("SpecialSkill@" + str(skill_folder_name))
            action_data = extract_track_data(special_skill_bundle_data, special_skill_sequence_setting)
            # print(action_data)

            for action in action_data:
                attack_data, move_data, update_data = adapt_action(action, character_id)
                # attack_data, move_data = convert_enemy_action_data_to_sequence_data(action_data, character_id)

                if attack_data != {}:
                    attacks.append(attack_data)

                if move_data != {}:
                    moves.append(move_data)

                if update_data != {}:
                    updates.append(update_data)

        attack_setting = {
            "CharacterId": character_id,
            "Category": "AttackSetting",
            "Data": json.dumps({"AttackSetting": attacks})
        }

        move_setting = {
            "CharacterId": character_id,
            "Category": "MoveSetting",
            "Data": json.dumps({"MoveSetting": moves})
        }

        sequence_master_data.append(attack_setting)
        sequence_master_data.append(move_setting)

    return sequence_master_data


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
            action_data = extract_track_data(animation_data, sequence_setting)

            # print("Owner ID", owner_id)

            attacks = []
            moves = []
            updates = []

            for action in action_data:
                attack_data, move_data, update_data = adapt_action(action, owner_id)
                # attack_data, move_data = convert_enemy_action_data_to_sequence_data(action_data, character_id)

                if attack_data != {}:
                    attacks.append(attack_data)

                if move_data != {}:
                    moves.append(move_data)

                if update_data != {}:
                    updates.append(update_data)

            attack_setting = {
                "EnemyId": owner_id,
                "Category": "AttackSetting",
                "Data": json.dumps({"AttackSetting": attacks})
            }

            move_setting = {
                "EnemyId": owner_id,
                "Category": "MoveSetting",
                "Data": json.dumps({"MoveSetting": moves})
            }

            sequence_master_data.append(attack_setting)
            sequence_master_data.append(move_setting)

    return sequence_master_data
