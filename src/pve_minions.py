"""Bounded approval for native-verified static minion presets."""

import json
import math
import struct


def decoy_max_hp(owner_max_hp, hp_rate, add_multipliers=()):
    """Native CalcDecoyHP for an explicit AddMultiply-only buff set.

    Caller must supply live authoritative owner HP and resolved buff values.
    This helper does not infer equipped skills or validate other reflection
    types, and must not use reported client HP as that authority.
    """
    if type(owner_max_hp) is not int or not 0 <= owner_max_hp < 2**31:
        raise ValueError('Invalid owner maximum HP.')
    def single(value):
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError('Invalid decoy calculation value.')
        try:
            result = struct.unpack('<f', struct.pack('<f', value))[0]
        except (OverflowError, struct.error):
            raise ValueError('Decoy calculation exceeds native float range.') from None
        if not math.isfinite(result):
            raise ValueError('Decoy calculation exceeds native float range.')
        return result
    rate = single(hp_rate)
    rate = 0.5 if rate <= 0 else rate
    base = single(single(owner_max_hp) * rate)
    multiplier = 1.0
    for effect in add_multipliers:
        multiplier = single(multiplier + single(single(effect) - 1.0))
    value = max(0.0, single(base * multiplier))
    result = math.ceil(value)
    if not 0 <= result < 2**31:
        raise ValueError('Decoy HP exceeds native integer range.')
    return result


class PreparedBitSummons:
    """Approve pl021's installed Bit timeline without accepting dynamic assets.

    Uses the frozen battle master and registered player parent. This is spawn
    compatibility policy, not validation of client combat or skill timing.
    Other presets and replacement identities need their own verified bindings.
    """

    def __call__(self, account, room, request):
        if request.get(5) != 'Bit' or request.get(6, '') != '':
            return False
        character = room.get('BattleCharacters', {}).get(account)
        if not character or character.get(1) != 'pl021' or character.get(2) != 'pl021':
            return False
        parent = request[2][1]
        player = room.get('PlayerObjects', {}).get(parent)
        if not player or player[0] != account:
            return False
        response = room.get('PreparedBattle', {}).get(account)
        if response is None:
            return False
        rows = [row for row in response['MasterGroup']['characters']
                if row.get('CharacterId') == 'pl021']
        if len(rows) != 1:
            raise ValueError('One frozen summon character master required.')
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError('Duplicate summon parameter field.')
                result[key] = value
            return result
        params = json.loads(rows[0]['UniqueParamData'], object_pairs_hook=unique)
        limits = [row['Value'] for row in params['m_Param_Int']
                  if row.get('Key') == 'MaxMinionCount']
        if len(limits) != 1 or type(limits[0]) is not int or not 1 <= limits[0] <= 32:
            raise ValueError('Bounded installed summon limit required.')
        guid = request[1][1]
        objects = room.get('MinionObjects', {})
        existing = objects.get(guid)
        if existing is not None:
            return (existing[0] == account and existing[1][2][1] == parent
                    and existing[1][5] == 'Bit' and existing[1][6] == '')
        # One selected character per account: changing/recreating its parent
        # GUID must not grant another set of summon slots.
        count = sum(owner == account and value[5] == 'Bit'
                    for owner, value in objects.values())
        return count < limits[0]


class PreparedDecoyRelay:
    """Relay configured equipped decoy skills with client-owned combat state.

    Bindings map spell IDs to (base prefab, tuple of effect prefabs). HP is a
    bounded client combat claim, never server reward or progress authority.
    maximum is an explicit operator limit on live decoys per account.
    """
    def __init__(self, bindings, maximum):
        if type(maximum) is not int or not 1 <= maximum <= 64:
            raise ValueError('Bounded decoy relay limit required.')
        self.bindings = {}
        for spell, paths in bindings.items():
            if (type(spell) is not str or not spell or type(paths) is not tuple
                    or len(paths) != 2 or type(paths[0]) is not str or not paths[0]
                    or type(paths[1]) is not tuple
                    or any(type(path) is not str or not path for path in paths[1])):
                raise ValueError('Verified decoy spell and prefab binding required.')
            self.bindings[spell] = paths
        self.maximum = maximum

    def __call__(self, account, room, request):
        if request.get(5) != 'MagicDecoy':
            return False
        player = room.get('PlayerObjects', {}).get(request[2][1])
        character = room.get('BattleCharacters', {}).get(account)
        if not player or player[0] != account or not character:
            return False
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError('Duplicate decoy field.')
                result[key] = value
            return result
        try:
            params = json.loads(request.get(6, ''), object_pairs_hook=unique)
        except (ValueError, TypeError, RecursionError):
            return False
        if (type(params) is not dict
                or set(params) != {'MaxHP', 'HP', 'Base_LoadPath', 'AddPrefabInfos'}
                or type(params['MaxHP']) is not int or not 0 <= params['MaxHP'] < 2**31
                or type(params['HP']) is not int or not 0 <= params['HP'] <= params['MaxHP']
                or type(params['Base_LoadPath']) is not str
                or type(params['AddPrefabInfos']) is not list):
            return False
        paths = (params['Base_LoadPath'], tuple(params['AddPrefabInfos']))
        response = room.get('PreparedBattle', {}).get(account)
        if response is None:
            return False
        owned = {row['EquipmentId'] for row in response['CharacterDetail']['userEquipments']}
        equipment = response['MasterGroup']['equipments']
        # Native WeaponSpell stores equipment IDs; SpellId is on its master.
        if not any(key in owned and any(row.get('EquipmentId') == key
                   and self.bindings.get(row.get('SpellId')) == paths for row in equipment)
                   for key in character[10]):
            return False
        objects = room.get('MinionObjects', {})
        existing = objects.get(request[1][1])
        if existing is not None:
            # RoomService separately freezes identity/prefabs/maxHP on recovery.
            return existing[0] == account
        return sum(owner == account and value[5] == 'MagicDecoy'
                   for owner, value in objects.values()) < self.maximum
