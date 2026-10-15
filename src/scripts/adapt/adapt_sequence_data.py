from pathlib import Path
import json

from .sequence_data.extract_sequence_data import extract_SequenceSetting_files
from .sequence_data.adapt_enemy_sequence import adapt_enemy_sequence, adapt_character_sequences


def extract_all_SequenceSetting_files(downloaded_characters_base_folder_path, output_folder):
    # download/characters/ has both character and enemy folders

    # Enemies
    print("Extracting enemy SequenceSetting file")
    enemy_files = sorted(Path(downloaded_characters_base_folder_path).rglob("enemy/em*/*.ab"))
    extract_SequenceSetting_files(enemy_files, output_folder / "enemy")
    # print(enemy_files)

    # Characters
    print("Extracting character SequenceSetting file")
    player_files = sorted(Path(downloaded_characters_base_folder_path).rglob("player/pl[0-9]*/prefabs/*.ab"))
    extract_SequenceSetting_files(player_files, output_folder / "player")

    # for path in player_files:
    #    print(str(path))


def adapt_sequence_data_from_animation_data(base_sequence_setting_folder, characters_download_folder):
    print("Extracting and adapting enemy sequence data")
    enemy_sequence_folder = base_sequence_setting_folder / "enemy"
    enemy_animations_folder = characters_download_folder / "enemy" / "animations"

    enemy_sequence_data = []
    # enemy_sequence_data = adapt_enemy_sequence(enemy_sequence_folder, enemy_animations_folder)

    character_sequence_folder = base_sequence_setting_folder / "player"
    downloaded_player_data_folder = characters_download_folder / "player"

    character_sequence_data = adapt_character_sequences(character_sequence_folder, downloaded_player_data_folder)

    # print("Extracting and adapting character sequence data")

    return character_sequence_data, enemy_sequence_data
