"""Recover costume-specific combat masters from Unity sequence bundles."""

from copy import deepcopy
import json
from pathlib import Path

import UnityPy


# Serialized clip names and their client AttackClipData member/setting field.
ATTACK_CLIPS = {
    'Attack Clip': ('clip_Attack', 'attackClipSettings'),
    'GunAttack Clip': ('clip_Gun', 'gunAttackClipSettings'),
    'LookTargetGunAttack Clip': ('clip_LookGun', 'gunAttackClipSettings'),
    'ThrowWeapon Clip': ('clip_ThrowWeapon', 'gunAttackClipSettings'),
    'GrenadeAttack Clip': ('clip_Grenade', 'gunAttackClipSettings'),
    'PutShooting Clip': ('clip_PutShoot', 'gunAttackClipSettings'),
    'Grenade PlungingFireAttack Clip': ('clip_Plunging', 'gunAttackClipSettings'),
    'Summon Clip': ('clip_Summon', 'clipSettings'),
}


def sequence_bundle_names(manifest):
    """Animation bundles are unnecessary; only download sequence assets."""
    return [entry for entry in manifest['m_Entries']
            if '/specialskill/' in entry['Name'].lower()
            and '/specialskill@' in entry['Name'].lower()]


def recover_sequence(owner, sequence, resolve):
    """Follow timeline references in track order, preserving serialized indices.

    Timeline frame times stay in the client's assets. Masters carry the setting
    payloads, addressed by ClipIndex, rather than by Unity object enumeration.
    """
    name = sequence['m_Name']
    attack, update, moves = {}, {}, {}
    base = None

    def put(target, index, field, value):
        if not isinstance(index, int) or not 0 <= index < 4096:
            raise ValueError(f'{name}: invalid clip index {index}')
        row = target.setdefault(index, {})
        # Repeated timeline occurrences may share a master index. Native
        # AddClipData retains its first occurrence rather than overwriting it.
        row.setdefault(field, deepcopy(value))

    for track in sequence['tracks']:
        for clip in track['clips']:
            data = resolve(clip['behaviourPrefab'])
            kind = data['m_Name']
            if kind == 'Animator Clip' and data.get('isAttack'):
                base = deepcopy(data['attackBaseInfo'])
            elif kind in ATTACK_CLIPS:
                member, setting_field = ATTACK_CLIPS[kind]
                settings = data[setting_field]
                index = settings['ClipIndex']
                put(attack, index, member, settings)
                # One shared hit payload per index. Native AddClipData keeps
                # the first occurrence; retain additional typed payloads too.
                if 'hitSetting' not in attack[index]:
                    put(attack, index, 'hitSetting', data['hitSettings'])
            elif kind == 'UpdateAttackInfo Clip':
                put(update, data['clipIndex'], 'attackBaseInfo', data['attackBaseInfo'])
            elif kind == 'SpecialSkillMagic Clip':
                settings = data['clipSettings']
                put(update, settings['ClipIndex'], 'clip_SpecialSkillMagic', settings)
            elif kind == 'Move Clip':
                put(moves, data['clipIndex'], 'direction', data['direction'])
                put(moves, data['clipIndex'], 'speed', data['speed'])
            elif 'hitSettings' in data or 'attackClipSettings' in data:
                raise ValueError(f'{name}: unsupported combat clip {kind}')

    def indexed(category, clips, **extra):
        count = max(clips, default=-1) + 1
        return {category: [{'id': owner, 'sequenceName': name,
                           **extra, 'totalClipCount': count, 'clipCount': [],
                           'clipDatas': [clips.get(i, {}) for i in range(count)]}]}

    result = []
    if attack or base is not None:
        if base is None:
            raise ValueError(f'{name}: missing attack base info')
        result.append(indexed('AttackSetting', attack, baseInfo=base))
    if update:
        result.append(indexed('UpdateParameterSetting', update))
    if moves:
        count = max(moves) + 1
        result.append({'MoveSetting': [{'id': owner, 'sequenceName': name,
            'totalMoveCount': count, 'moveCount': [],
            'direction': [moves.get(i, {}).get('direction', {'x': 0, 'y': 0, 'z': 0})
                          for i in range(count)],
            'speed': [moves.get(i, {}).get('speed', 0) for i in range(count)]}]})
    return result


def recover_bundle(path, owner):
    env = UnityPy.load(str(path))
    sequences = [obj.read_typetree() for obj in env.objects
                 if obj.type.name == 'MonoBehaviour']
    roots = [data for data in sequences
             if data.get('m_Name', '').startswith('SpecialSkill@') and 'tracks' in data]
    if len(roots) != 1:
        raise ValueError(f'{Path(path).name}: expected one special skill sequence')
    objects = {obj.path_id: obj for obj in env.objects}

    def resolve(ref):
        if ref['m_FileID'] != 0:
            raise ValueError('Special skill clip references an external bundle')
        return objects[ref['m_PathID']].read_typetree()

    return recover_sequence(owner, roots[0], resolve)


def recover_special_skills(bundle_root):
    result = []
    bundle_root = Path(bundle_root)
    manifest_path = bundle_root.parent / 'extract/manifest.json'
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        paths = [bundle_root / (entry['Name'] + '_' + entry['Version'] + '.ab')
                 for entry in sequence_bundle_names(manifest)]
        if any(not path.is_file() for path in paths):
            raise FileNotFoundError('Special skill sequence bundles are missing; rerun setup to download them')
    else:
        paths = list(bundle_root.glob('characters/player/*/specialskill/*/specialskill@*.ab'))
    seen = set()
    for path in sorted(paths):
        key = (path.parents[2].name, path.parent.name)
        if key in seen:
            raise ValueError('Duplicate special skill bundle versions; provide the installed manifest')
        seen.add(key)
        result.extend(recover_bundle(path, path.parents[2].name))
    return result
