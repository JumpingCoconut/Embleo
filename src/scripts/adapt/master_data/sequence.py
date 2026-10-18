import json
from pathlib import Path

from .special_skill import recover_special_skills, recover_minion_commands
from .healing_circle import recover_healing_circles, replace_recovered_attacks
from ..sequence_data.tracks.Attack import normalize_IgnoreHitLayer as _normalize_layer_masks


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

    # Use upstream's complete asset adapters for both setup and CLI regeneration.
    # Merge by sequence name: debug-only spells and recovered costume/minion
    # payloads must not disappear when an asset category has partial coverage.
    bundle_root = Path(bundle_root)
    if (bundle_root / 'characters').exists():
        from ..extract_sequence_data import extract_all_SequenceSetting_files
        from ..adapt_sequence_data import adapt_all_sequence_data
        settings = bundle_root.parent / 'extract/SequenceSetting'
        extract_all_SequenceSetting_files(bundle_root / 'characters', settings)
        characters, enemies = adapt_all_sequence_data(settings, bundle_root / 'characters')
        character_sequences = merge_sequence_masters(character_sequences, characters, 'CharacterId')
        enemy_sequences = merge_sequence_masters(enemy_sequences, enemies, 'EnemyId')

    with open(output_folder / "CharacterSequenceMasterData.json", "w") as of:
        json.dump(character_sequences, of, indent=4)

    with open(output_folder / "EnemySequenceMasterData.json", "w") as of:
        json.dump(enemy_sequences, of, indent=4)


def merge_sequence_masters(existing, recovered, owner_key):
    """Prefer asset payloads while retaining debug-only sequences and fields."""
    result = {(row[owner_key], row['Category']): row for row in existing}
    for row in recovered:
        owner, category = row[owner_key], row['Category']
        key = (owner, category)
        incoming = json.loads(row['Data'])[category]
        old = json.loads(result[key]['Data'])[category] if key in result else None
        if category == 'ResourceList':
            values = (old or {}).get('values', []) + incoming['values']
            resources = {(r['type'], r['value']): r for r in values}
            merged = {**(old or {}), **incoming, 'values': list(resources.values())}
        else:
            entries = {entry['sequenceName']: entry for entry in (old or [])}
            for entry in incoming:
                name = entry['sequenceName']
                previous = entries.get(name, {})
                entry = {**previous, **entry}
                # EnemyAnimator and some non-attack player clips don't carry
                # baseInfo. An absent asset value must not erase debug defaults.
                if category == 'AttackSetting' and entry.get('baseInfo') is None and 'baseInfo' in previous:
                    entry['baseInfo'] = previous['baseInfo']
                entries[name] = entry
            merged = list(entries.values())
        result[key] = {**result.get(key, {}), **row, 'Data': json.dumps(_normalize_layer_masks({category: merged}))}
    return list(result.values())


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Regenerate combat sequence masters from installed assets')
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    args = parser.parse_args()
    adapt_debug_sequences_master_data(
        args.data_root / 'extract/masterdatadebug/SequenceMasterDataObject.json',
        args.data_root / 'masterdata', args.data_root / 'download')
