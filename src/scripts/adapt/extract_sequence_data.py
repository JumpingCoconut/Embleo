import os
import UnityPy
import json
from pathlib import Path

SequenceSetting_script_path_number = 6600754288517090867  # No m_Name. Have to improvise


def get_group_and_id_from_file_path(path):
    # path = str(path)

    # emXXXX/emXXXX_YYY_dfdf.ab
    # prefabs/plXXX

    id = str(path.name)

    # Trim _assbsbbsbdhffj.ab
    id = id[:id.rfind("_")]
    group = ""

    if "enemy" in str(path):
        # Trim _YYY
        group = id[:id.rfind("_")]

    return group, id


def extract_SequenceSetting(asset_bundle_path):
    SequenceSetting = {
        "owner_id": "",
        "basePath": "",
        "sequenceNames": [],
        "keyAndSequences": []
    }

    _, owner_id = get_group_and_id_from_file_path(asset_bundle_path)
    SequenceSetting["owner_id"] = owner_id

    character_data = UnityPy.load(str(asset_bundle_path))

    for obj in character_data.objects:
        if obj.type.name == "MonoBehaviour":
            setting = obj.parse_as_dict()

            if setting["m_Script"]["m_PathID"] == SequenceSetting_script_path_number:
                # print(setting)

                SequenceSetting["basePath"] = setting["basePath"]

                for sequenceEntry in setting["keyAndSequences"]:
                    action_name = sequenceEntry["path"]
                    SequenceSetting["sequenceNames"].append(action_name)

                SequenceSetting["keyAndSequences"] = setting["keyAndSequences"]

    return SequenceSetting


def extract_SequenceSetting_files(file_paths, output_folder):
    SequenceSetting_dict = {}

    for path in file_paths:
        setting = extract_SequenceSetting(path)

        group_name, owner_id = get_group_and_id_from_file_path(path)

        if "enemy" in str(file_paths[0]):
            if group_name not in SequenceSetting_dict:
                SequenceSetting_dict[group_name] = {}

            SequenceSetting_dict[group_name][owner_id] = setting
        else:
            SequenceSetting_dict[owner_id] = setting

    # Merge Charles' Gems SequenceSetting with his own
    if "pl021_bit" in SequenceSetting_dict and "pl021" in SequenceSetting_dict:
        gem_action_list = SequenceSetting_dict["pl021_bit"]["sequenceNames"]
        SequenceSetting_dict["pl021"]["sequenceNames"].extend(gem_action_list)
        gem_timeline_references = SequenceSetting_dict["pl021_bit"]["keyAndSequences"]
        SequenceSetting_dict["pl021"]["keyAndSequences"].extend(gem_timeline_references)
        SequenceSetting_dict.pop("pl021_bit")

    # make sure that the dir of that path exists
    print(output_folder)
    os.makedirs(output_folder, exist_ok=True)

    for key in SequenceSetting_dict.keys():
        output_file = output_folder / "{}.json".format(key)
        # print(output_file)

        settings = SequenceSetting_dict[key]

        with open(output_file, "w", encoding="utf8") as of:
            json.dump(settings, of, ensure_ascii=False, indent=4)
            # print("Saved", output_file)


def extract_all_SequenceSetting_files(downloaded_characters_base_folder_path, output_folder):
    # download/characters/ has both character and enemy folders

    # Characters
    print("Extracting character SequenceSetting file")
    player_files = sorted(Path(downloaded_characters_base_folder_path).rglob("player/pl[0-9]*/prefabs/*.ab"))
    extract_SequenceSetting_files(player_files, output_folder / "player")

    # Enemies
    print("Extracting enemy SequenceSetting file")
    enemy_files = sorted(Path(downloaded_characters_base_folder_path).rglob("enemy/em*/*.ab"))
    extract_SequenceSetting_files(enemy_files, output_folder / "enemy")
    # print(enemy_files)

    # for path in player_files:
    #    print(str(path))