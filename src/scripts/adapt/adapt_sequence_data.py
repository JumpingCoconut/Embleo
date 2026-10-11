from pathlib import Path

from .sequence_data.extract_sequence_data import extract_SequenceSetting_files


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

