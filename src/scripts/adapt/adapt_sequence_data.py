from pathlib import Path
import json

from .sequence_data.extract_sequence_data import extract_SequenceSetting_files, installed_bundle_paths
from .sequence_data.adapt_enemy_sequence import adapt_enemy_sequence


def merge_enemy_movement(existing, recovered):
    """Add recovered movement without replacing existing combat payloads."""
    by_key = {(row['EnemyId'], row['Category']): row for row in existing}
    for row in recovered:
        if row['Category'] != 'MoveSetting':
            raise ValueError('Only completed movement extraction can replace masters')
        key = (row['EnemyId'], row['Category'])
        native = json.loads(row['Data'])['MoveSetting']
        old = json.loads(by_key[key]['Data'])['MoveSetting'] if key in by_key else []
        merged = {entry['sequenceName']: entry for entry in old}
        merged.update({entry['sequenceName']: entry for entry in native})
        by_key[key] = row | {'Data': json.dumps({'MoveSetting': list(merged.values())})}
    return list(by_key.values())


def extract_all_SequenceSetting_files(downloaded_characters_base_folder_path, output_folder):
    # download/characters/ has both character and enemy folders

    # Enemies
    print("Extracting enemy SequenceSetting file")
    enemy_files = installed_bundle_paths(downloaded_characters_base_folder_path, "enemy/em*/*.ab")
    extract_SequenceSetting_files(enemy_files, output_folder / "enemy")
    # print(enemy_files)

    # Characters
    # Player costume masters use the separate special_skill recovery pipeline.

    # for path in player_files:
    #    print(str(path))


def adapt_sequence_data_from_animation_data(base_sequence_setting_folder, characters_download_folder):
    print("Extracting and adapting enemy sequence data")
    enemy_sequence_folder = base_sequence_setting_folder / "enemy"
    enemy_animations_folder = characters_download_folder / "enemy" / "animations"

    enemy_sequence_data = adapt_enemy_sequence(enemy_sequence_folder, enemy_animations_folder)

    # print("Extracting and adapting character sequence data")

    return [], enemy_sequence_data
