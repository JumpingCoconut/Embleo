"""Recover regular healing summons whose debug masters have stale clip indices."""

import json
from pathlib import Path

from .special_skill import recover_bundle


HEALING_CIRCLE_SEQUENCES = {
    'characters/player/pl009/sequences/attack2',
    'characters/player/pl009/sequences/attack8',
}


def healing_circle_bundle_names(manifest):
    return [entry for entry in manifest['m_Entries']
            if entry['Name'].lower() in HEALING_CIRCLE_SEQUENCES]


def recover_healing_circles(bundle_root):
    bundle_root = Path(bundle_root)
    manifest_path = bundle_root.parent / 'extract/manifest.json'
    if not manifest_path.exists():
        raise FileNotFoundError('Installed manifest is required to recover healing circles')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
    entries = healing_circle_bundle_names(manifest)
    if {entry['Name'].lower() for entry in entries} != HEALING_CIRCLE_SEQUENCES:
        raise ValueError('Manifest is missing required healing circle sequences')
    result = []
    for entry in entries:
        path = bundle_root / (entry['Name'] + '_' + entry['Version'] + '.ab')
        if not path.is_file():
            raise FileNotFoundError('Healing circle bundles are missing; rerun setup to download them')
        # Update/movement masters are unchanged. Recover only the attack lookup
        # layout and its resources, without replacing unrelated character data.
        result.extend(row for row in recover_bundle(path, entry['Name'].split('/')[2])
                      if 'AttackSetting' in row or 'ResourceList' in row)
    return result


def replace_recovered_attacks(existing, recovered):
    """Replace by owner/name, not append a second conflicting lookup record."""
    replacements = {(entry['id'], entry['sequenceName']): entry
                    for row in recovered for entry in row.get('AttackSetting', [])}
    result = []
    for row in existing:
        entries = []
        for entry in row['AttackSetting']:
            replacement = replacements.pop((entry['id'], entry['sequenceName']), None)
            entries.append({**entry, **replacement} if replacement is not None else entry)
        result.append({**row, 'AttackSetting': entries})
    if replacements:
        result.append({'AttackSetting': list(replacements.values())})
    return result
