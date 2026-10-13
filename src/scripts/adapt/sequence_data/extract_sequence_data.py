import os
import UnityPy
import json
from pathlib import Path

SequenceSetting_path_number = 6600754288517090867  # No m_Name. Have to improvise


def installed_bundle_paths(characters_folder, pattern):
    characters_folder = Path(characters_folder)
    manifest = characters_folder.parents[1] / 'extract/manifest.json'
    if not manifest.exists():
        return sorted(characters_folder.rglob(pattern))
    entries = json.loads(manifest.read_text(encoding='utf-8-sig'))['m_Entries']
    paths = []
    for entry in entries:
        if not entry['Name'].startswith('characters/'):
            continue
        relative = Path(entry['Name'][len('characters/'):] + '_' + entry['Version'] + '.ab')
        if relative.match(pattern):
            path = characters_folder / relative
            if not path.is_file():
                raise FileNotFoundError('Enemy sequence bundles are missing; rerun setup')
            paths.append(path)
    return sorted(paths)


def get_group_and_id_from_file_path(path):
    path = str(path)

    # emXXXX/emXXXX_YYY_dfdf.ab
    # prefabs/plXXX

    if "/" in path:
        id = path[path.rfind("/") + 1:]
    else:
        id = path[path.rfind("\\") + 1:]

    # Trim _assbsbbsbdhffj.ab
    id = id[:id.rfind("_")]
    group = ""

    if "enemy" in path:
        # Trim _YYY
        group = id[:id.rfind("_")]

    return group, id


def extract_SequenceSetting(asset_bundle_path):
    SequenceSetting = {
        "owner_id": "",
        "basePath": "",
        "sequenceNames": []
    }

    asset_bundle_path = str(asset_bundle_path)

    _, owner_id = get_group_and_id_from_file_path(asset_bundle_path)
    SequenceSetting["owner_id"] = owner_id

    character_data = UnityPy.load(str(asset_bundle_path))

    for obj in character_data.objects:
        if obj.type.name == "MonoBehaviour":
            setting = obj.read_typetree()

            path_number = setting["m_Script"]["m_PathID"]
            # path_number = SequenceSetting_path_number

            if path_number == SequenceSetting_path_number:
                # print(setting)

                SequenceSetting["basePath"] = setting["basePath"]

                for sequenceEntry in setting["keyAndSequences"]:
                    action_name = sequenceEntry["path"]
                    SequenceSetting["sequenceNames"].append(action_name)

    return SequenceSetting


def extract_SequenceSetting_files(file_paths, output_folder):
    SequenceSetting_dict = {}

    for path in file_paths:
        setting = extract_SequenceSetting(path)

        group_name, owner_id = get_group_and_id_from_file_path(path)

        if "enemy" in str(path):
            if group_name not in SequenceSetting_dict:
                SequenceSetting_dict[group_name] = {}

            SequenceSetting_dict[group_name][owner_id] = setting
        else:
            SequenceSetting_dict[owner_id] = setting

    # make sure that the dir of that path exists
    print(output_folder)
    os.makedirs(output_folder, exist_ok=True)

    for id in SequenceSetting_dict.keys():
        output_file = output_folder / "{}.json".format(id)
        # print(output_file)

        settings = SequenceSetting_dict[id]

        with open(output_file, "w", encoding="utf8") as of:
            json.dump(settings, of, ensure_ascii=False, indent=4)
            # print("Saved", output_file)
