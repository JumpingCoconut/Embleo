from pathlib import Path
import json

from .sequence_data.adapt_sequence import adapt_enemy_sequence, adapt_character_sequences


def adapt_all_sequence_data(base_sequence_setting_folder, characters_download_folder):
    character_sequence_folder = base_sequence_setting_folder / "player"
    downloaded_player_data_folder = characters_download_folder / "player"

    print("Extracting and adapting character sequence data")
    character_sequence_data = adapt_character_sequences(character_sequence_folder, downloaded_player_data_folder)

    enemy_sequence_folder = base_sequence_setting_folder / "enemy"
    enemy_animations_folder = characters_download_folder / "enemy" / "animations"

    print("Extracting and adapting enemy sequence data")
    enemy_sequence_data = []
    enemy_sequence_data = adapt_enemy_sequence(enemy_sequence_folder, enemy_animations_folder)

    return character_sequence_data, enemy_sequence_data
