import json
from pathlib import Path

from .special_skill import recover_special_skills, recover_minion_commands
from .healing_circle import recover_healing_circles, replace_recovered_attacks


def _normalize_layer_masks(value):
    if isinstance(value, list):
        return [_normalize_layer_masks(item) for item in value]
    if not isinstance(value, dict):
        return value

    result = {key: _normalize_layer_masks(item) for key, item in value.items()}
    mask = result.get('IgnoreHitLayer')
    if isinstance(mask, dict) and 'm_Bits' in mask and 'm_Mask' not in mask:
        # Unity assets serialize LayerMask as m_Bits; the client's reflection
        # JSON reader instead assigns its private signed-int field m_Mask.
        bits = mask.pop('m_Bits')
        if isinstance(bits, int) and 0x80000000 <= bits <= 0xffffffff:
            bits -= 0x100000000
        mask['m_Mask'] = bits
    return result


def adapt_debug_sequence_list(sequence_list):
    adapted_sequence_list = []

    grouped = {}
    for wrapper in sequence_list:
        category = next(iter(wrapper))
        for entry in wrapper[category]:
            grouped.setdefault((entry['id'], category), []).append(entry)

    for (ID, category), entries in grouped.items():
        setting = {category: entries}
        if category == 'ResourceList':
            resources = {}
            for entry in entries:
                for resource in entry['values']:
                    resources.setdefault((resource['type'], resource['value']), resource)
            # ResourceListWrapper contains one ResourceListInfo, not an array.
            setting = {category: {'id': ID, 'values': list(resources.values())}}

        new_seq = {}

        if "pl" in ID:
            new_seq["CharacterId"] = ID
        else:
            new_seq["EnemyId"] = ID

        new_seq["Category"] = category
        new_seq["Data"] = json.dumps(_normalize_layer_masks(setting))  # Born to be a JSON, forced to be a string

        adapted_sequence_list.append(new_seq)

    return adapted_sequence_list


def adapt_debug_sequences_master_data(input_file_path, output_folder, bundle_root=None):
    input_file_path = Path(input_file_path)
    output_folder = Path(output_folder)
    with input_file_path.open(encoding='utf-8') as f:
        debug_seqs = json.load(f)

    # In original file the sequences are grouped by type
    attack_list = debug_seqs["attackList"]
    move_list = debug_seqs["moveList"]
    parameter_list = debug_seqs["updateParameterList"]
    # no_use = debug_seqs["noUse"]  # Well, we are using it, all right

    # Debug masters omit equipment-specific timelines. Keep their asset names
    # as lookup keys so swapping costumes selects the matching combat payload.
    if bundle_root is None:
        bundle_root = input_file_path.resolve().parents[2] / 'download'
    healing_circles = recover_healing_circles(bundle_root)
    attack_list = replace_recovered_attacks(attack_list, healing_circles)
    adapted_sequences = adapt_debug_sequence_list([
        *attack_list, *move_list, *parameter_list,
        *(row for row in healing_circles if 'ResourceList' in row),
        *recover_special_skills(bundle_root), *recover_minion_commands(bundle_root)])

    character_sequences = []
    enemy_sequences = []

    for entry in adapted_sequences:
        if "CharacterId" in entry:
            character_sequences.append(entry)
        else:
            enemy_sequences.append(entry)

    # Sort by ID
    character_sequences = sorted(character_sequences, key=lambda x: x['CharacterId'])
    enemy_sequences = sorted(enemy_sequences, key=lambda x: x['EnemyId'])

    # Keep CLI regeneration and fresh setup on the same sequence pipeline.
    bundle_root = Path(bundle_root)
    if (bundle_root / 'characters/enemy').exists():
        from ..adapt_sequence_data import (
            extract_all_SequenceSetting_files,
            adapt_sequence_data_from_animation_data, merge_enemy_movement,
        )
        settings = bundle_root.parent / 'extract/SequenceSetting'
        extract_all_SequenceSetting_files(bundle_root / 'characters', settings)
        _, recovered = adapt_sequence_data_from_animation_data(settings, bundle_root / 'characters')
        enemy_sequences = merge_enemy_movement(enemy_sequences, recovered)

    with open(output_folder / "CharacterSequenceMasterData.json", "w") as of:
        json.dump(character_sequences, of, indent=4)

    with open(output_folder / "EnemySequenceMasterData.json", "w") as of:
        json.dump(enemy_sequences, of, indent=4)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Regenerate combat sequence masters from installed assets')
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    args = parser.parse_args()
    adapt_debug_sequences_master_data(
        args.data_root / 'extract/masterdatadebug/SequenceMasterDataObject.json',
        args.data_root / 'masterdata', args.data_root / 'download')
