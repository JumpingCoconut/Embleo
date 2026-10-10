"""Native character/equipment level curves; loadout/passive totals are separate."""

import math
import struct
import json
from copy import deepcopy


class PartyCharacterPresentation:
    """Installed defaults for normal MakeDeckCharacters -> LoadParty.

    CharacterData uses the party ID as MasterDataID. PvE party setup can
    replace the original selection with a costume's ReplaceCharacterId;
    callers must resolve that identity before requesting presentation.
    """
    def __init__(self, character_masters, equipment_ids, equipment_masters=()):
        self._defaults = {}
        self._replacements = {}
        for row in equipment_masters:
            key, replacement = row.get('EquipmentId'), row.get('ReplaceCharacterId')
            if type(key) is not str or not key or key in self._replacements:
                raise ValueError('Invalid replacement equipment master.')
            if replacement is not None and type(replacement) is not str:
                raise ValueError('Invalid replacement character ID.')
            self._replacements[key] = replacement or ''
        installed = set(equipment_ids)
        self._installed = installed
        if any(type(key) is not str or not key for key in installed):
            raise ValueError('Invalid installed visual equipment IDs.')
        for row in character_masters:
            key = row.get('CharacterId')
            if type(key) is not str or not key or key in self._defaults:
                raise ValueError('Invalid or duplicate presentation master.')
            try:
                parameters = json.loads(row['UniqueParamData'])
            except (KeyError, ValueError, TypeError):
                raise ValueError('Invalid character presentation parameters.') from None
            entries = parameters.get('m_Param_StringArray', []) if type(parameters) is dict else None
            if type(entries) is not list:
                raise ValueError('Invalid character presentation arrays.')
            matches = [entry for entry in entries if type(entry) is dict
                       and entry.get('Key') == 'VisualEquipments']
            if len(matches) > 1:
                raise ValueError('Duplicate default character visuals.')
            visual = matches[0].get('Value') if matches else None
            if matches and (type(visual) is not list or not 2 <= len(visual) <= 32
                    or any(type(item) is not str for item in visual)):
                raise ValueError('Default character visuals are not installed.')
            self._defaults[key] = {'MasterDataId': key, 'CharacterName': None,
                                   'VisualEquipments': list(visual) if visual is not None else None}

    def party_id(self, row):
        character_id = row['CharacterId']
        visual = row.get('VisualEquipment')
        if visual is not None and type(visual) is not list:
            raise ValueError('Invalid saved character visuals.')
        if visual:
            if type(visual[0]) is not str or visual[0] not in self._installed:
                raise ValueError('Party costume is not installed.')
            character_id = self._replacements.get(visual[0]) or character_id
        if character_id not in self._defaults:
            raise ValueError('Replacement character is not installed.')
        return character_id

    def character(self, character_id):
        if type(character_id) is not str or character_id not in self._defaults:
            raise ValueError('Character presentation is not installed.')
        result = deepcopy(self._defaults[character_id])
        visual = result['VisualEquipments']
        if visual is not None and any(item and item not in self._installed for item in visual):
            raise ValueError('Selected default character visuals are not installed equipment.')
        return result


def startup_buff_ids(character_master, installed_buff_ids):
    """Resolve native StartUpBuffIdList without changing installed parameters."""
    raw = character_master.get('UniqueParamData')
    if type(raw) is not str:
        raise ValueError('Invalid character unique parameters.')
    try:
        parameters = json.loads(raw) if raw else {}
    except (ValueError,TypeError):
        raise ValueError('Invalid character unique parameters.') from None
    if type(parameters) is not dict:
        raise ValueError('Invalid character unique parameters.')
    entries = parameters.get('m_Param_StringArray',[])
    if type(entries) is not list:
        raise ValueError('Invalid character string-array parameters.')
    matches = [row for row in entries if type(row) is dict and row.get('Key') == 'StartUpBuffIdList']
    if len(matches) > 1:
        raise ValueError('Duplicate startup buff parameter.')
    ids = matches[0].get('Value') if matches else []
    if type(ids) is not list or any(type(key) is not str or not key or key not in installed_buff_ids for key in ids):
        raise ValueError('Startup buff is invalid or not installed.')
    return list(ids)


class AccountCombatStats:
    """Read account-scoped saves through the caller's thread-safe read boundary."""
    def __init__(self, calculator, read_save, ordered_ids):
        self.calculator = calculator
        self.read_save = read_save
        self.ordered_ids = ordered_ids

    def character(self, account_id, character_id, level_overrides=None):
        if type(account_id) is not str or not account_id:
            raise ValueError('Account identity required for battle stats.')
        characters = self.read_save(account_id,'UserCharacter.json')
        equipment = self.read_save(account_id,'UserEquipment.json')
        ordering = self.ordered_ids(account_id)
        totals = self.calculator.character(character_id,characters,equipment,ordering,level_overrides)
        power = sum(totals.values())
        if not 0 <= power < 2**31:
            raise ValueError('Character power exceeds native range.')
        return totals | {'Power':power}


class PreparedCombatStats(AccountCombatStats):
    """Account-bound saves and stats for one battle preparation."""
    def __init__(self, calculator, account_id, snapshot, ordering):
        self.account_id = account_id
        self._snapshot = deepcopy(snapshot)
        self._ordering = deepcopy(ordering)
        self._combat_rows = deepcopy(self._snapshot['UserCharacter.json'])
        super().__init__(calculator, self.save, self._ordered)

    def party_character(self, character_id, presentation):
        """Clone the native replacement row without changing HTTP save data."""
        rows = [row for row in self._combat_rows if row.get('CharacterId') == character_id]
        if len(rows) != 1:
            raise ValueError('Unique owned party character required.')
        resolved = presentation.party_id(rows[0])
        if resolved != character_id:
            if any(row.get('CharacterId') == resolved for row in self._combat_rows):
                raise ValueError('Replacement character identity collision.')
            self._combat_rows.append(deepcopy(rows[0]) | {
                'CharacterId':resolved, 'BaseCharacterId':character_id})
        return resolved

    def character(self, account_id, character_id, level_overrides=None):
        self._check_account(account_id)
        totals = self.calculator.character(character_id, deepcopy(self._combat_rows),
            self.save(account_id, 'UserEquipment.json'), self._ordered(account_id), level_overrides)
        power = sum(totals.values())
        if not 0 <= power < 2**31:
            raise ValueError('Character power exceeds native range.')
        return totals | {'Power':power}

    def _check_account(self, account_id):
        if account_id != self.account_id:
            raise ValueError('Battle snapshot belongs to another account.')

    def save(self, account_id, name):
        self._check_account(account_id)
        return deepcopy(self._snapshot[name])

    def _ordered(self, account_id):
        self._check_account(account_id)
        return deepcopy(self._ordering)

    def initial_resources(self, account_id, character_id, level_overrides=None):
        """Normal client UpdateStatus -> SetupDebugStatus current resources.

        IncreaseStatusInfo receives calculated HP but no MP assignment on this
        path. This describes CharacterData before BattlePlayer startup buffs,
        not the separate float skill gauge or later owner-reported recovery.
        """
        totals = self.character(account_id, character_id, level_overrides)
        return {'Hp': totals['Hp'], 'Mp': 0}

    def battle_character(self, account_id, character_id, presentation, level_overrides=None):
        """Build paired HTTP/transport fields from this preparation's saves.

        presentation is resolved by installed server master/loadout policy,
        never passed through from a player's network creation request.
        """
        from prizm_battle import character_data_payload
        if (type(presentation) is not dict
                or set(presentation) != {'MasterDataId', 'CharacterName', 'VisualEquipments'}):
            raise ValueError('Resolved character presentation required.')
        resources = self.initial_resources(account_id, character_id, level_overrides)
        rows = [row for row in self._combat_rows
                if row.get('CharacterId') == character_id]
        if len(rows) != 1:
            raise ValueError('Unique owned character required.')
        row = rows[0]
        level = (level_overrides or {}).get(character_id, row['Level'])
        visual = row.get('VisualEquipment')
        if visual is not None and type(visual) is not list:
            raise ValueError('Invalid saved character visuals.')
        # SetVisualEquipments ignores null/short arrays, leaving LoadParty's
        # installed-master fallback active. Two slots are costume and weapon.
        if visual is None or len(visual) < 2:
            visual = presentation['VisualEquipments']
        if type(visual) is not list or len(visual) < 2:
            raise ValueError('Resolved character visuals require costume and weapon slots.')
        character = character_data_payload({
            1: character_id, 2: presentation['MasterDataId'],
            3: presentation['CharacterName'], 4: level, 5: row['Exp'],
            6: resources['Hp'], 7: resources['Mp'], 8: visual,
            9: [] if row.get('CostumeSpell') is None else row['CostumeSpell'],
            10: [] if row.get('WeaponSpell') is None else row['WeaponSpell'],
        })
        return {'PlayCharacter': {'characterId': character_id, 'level': level,
                                 'exp': character[5], 'hp': character[6], 'sp': character[7]},
                'CharacterData': character}


class SnapshotCombatStats:
    """Prepare a reusable battle-stat provider from one detached DB snapshot.

    ordering receives the snapshot, so ordering derived from player saves is
    consistent with equipment and characters. Additional requested saves can
    contain the episode/deck state needed by the production ordering resolver.
    """
    def __init__(self, calculator, database, ordering, extra_saves=()):
        self.calculator = calculator
        self.database = database
        self.ordering = ordering
        if (type(extra_saves) not in (list, tuple)
                or any(type(name) is not str or not name for name in extra_saves)):
            raise ValueError('Invalid battle snapshot save names.')
        self.names = tuple(dict.fromkeys(('UserCharacter.json', 'UserEquipment.json',
                                         *extra_saves)))

    def prepare(self, account_id):
        from accounts import read_save_snapshot
        snapshot = read_save_snapshot(self.database, account_id, self.names)
        ordering = deepcopy(self.ordering(deepcopy(snapshot)))

        return PreparedCombatStats(self.calculator, account_id, snapshot, ordering)


class EquipmentPassives:
    """Resolve installed setup buffs for owned main-slot equipment."""
    def __init__(self, equipment_masters, buff_masters):
        self.equipment = {}
        self.buffs = {}
        for row in equipment_masters:
            key, buffs = row.get('EquipmentId'),row.get('Buff')
            if (type(key) is not str or not key or key in self.equipment
                    or type(buffs) is not list or any(type(b) is not str for b in buffs)):
                raise ValueError('Invalid equipment buff master.')
            self.equipment[key] = tuple(buffs)
        for row in buff_masters:
            key,kind,values = row.get('ID'),row.get('EffectType'),row.get('EffectValue')
            if type(key) is not str or not key or key in self.buffs or type(kind) is not str:
                raise ValueError('Invalid buff master.')
            passive_effect_value(values,1)
            self.buffs[key] = (kind,None if values is None else tuple(values))

    def character(self, saved_character, owned_equipment):
        owned = {}
        for row in owned_equipment:
            key = row.get('EquipmentId')
            if type(key) is not str or not key or key in owned:
                raise ValueError('Invalid or duplicate owned equipment.')
            owned[key] = row
        result = {'Hp':[], 'Attack':[], 'Defense':[]}
        kinds = {'Setup_HP':'Hp','Setup_Attack':'Attack','Setup_Defense':'Defense'}
        for slot in ('Costume','WeaponMain','AccessoryMain'):
            keys = saved_character.get(slot) or []
            if type(keys) is not list:
                raise ValueError('Invalid passive equipment slot.')
            for key in keys:
                if key is None or key == '':
                    continue
                if type(key) is not str or key not in owned or key not in self.equipment:
                    raise ValueError('Passive equipment is not owned or installed.')
                for buff in self.equipment[key]:
                    # Equipment.setupBuff 0x176F9DC separates magic: entries.
                    if 'magic:' in buff:
                        continue
                    if buff not in self.buffs:
                        raise ValueError('Equipment buff is not installed.')
                    kind,values = self.buffs[buff]
                    if kind in kinds:
                        result[kinds[kind]].append(passive_effect_value(values,owned[key].get('SpLevel')))
        return result


def passive_effect_value(values, spell_level):
    # BuffMasterData.Info.GetEffectValueD 0x2FCA860.
    if type(spell_level) is not int or not -(2**31) <= spell_level < 2**31:
        raise ValueError('Invalid passive spell level.')
    if values is None:
        return 0.0
    if type(values) not in (list,tuple) or any(
            type(value) not in (int,float) or not math.isfinite(value) for value in values):
        raise ValueError('Invalid passive effect values.')
    if spell_level <= 0 or not values:
        return 0.0
    return float(values[min(spell_level,len(values))-1])


def passive_stat(base, effect_multipliers):
    # CharacterStatusParam.InputPassiveEffects 0x3610AB4 adds (effect - 1)
    # in slot order; get_AttackBuff 0x360F77C floors only after multiplication.
    if type(base) is not int or not -(2**31) <= base < 2**31:
        raise ValueError('Invalid passive base statistic.')
    bonus = 0.0
    for effect in effect_multipliers:
        if type(effect) not in (int,float) or not math.isfinite(effect):
            raise ValueError('Invalid passive multiplier.')
        bonus += effect - 1.0
    value = base * (1.0 + bonus)
    if not math.isfinite(value) or not -(2**31) <= value < 2**31:
        raise ValueError('Passive statistic exceeds native range.')
    return math.floor(value)


class RelatedCharacters:
    """Select owned same-faction characters from account content ordering."""
    def __init__(self, masters):
        self.factions = {}
        for row in masters:
            key,faction = row.get('CharacterId'),row.get('Faction')
            if (type(key) is not str or not key or key in self.factions
                    or type(faction) is not int):
                raise ValueError('Invalid or duplicate character faction master.')
            self.factions[key] = faction

    def select(self, target_id, ordered_ids, owned_characters):
        # HomeSceneUtility.GetRelationCharacters 0x32E3438 compares Faction
        # at native Character offset 0x1C, not Country at offset 0x18.
        owned = set()
        replacements = {}
        for row in owned_characters:
            key = row.get('CharacterId')
            if type(key) is not str or not key or key in owned:
                raise ValueError('Invalid or duplicate owned character.')
            owned.add(key)
            base = row.get('BaseCharacterId')
            if base is not None:
                if type(base) is not str or not base:
                    raise ValueError('Invalid replacement base character.')
                replacements[key] = base
        if type(target_id) is not str or target_id not in owned or target_id not in self.factions:
            raise ValueError('Target character is not owned or installed.')
        result,seen = [],set()
        for row in ordered_ids:
            kind = row.get('Type')
            if type(kind) is not int:
                raise ValueError('Invalid ordered content type.')
            if kind != 1:
                continue
            key = row.get('MasterDataId')
            if type(key) is not str or key not in owned or key not in self.factions or key in seen:
                raise ValueError('Ordered character is duplicate, unowned or not installed.')
            seen.add(key)
            # Native CreateStatusParam's relation callback excludes cloned
            # replacement rows and both the target and its original base row.
            if (key not in replacements and key != target_id
                    and key != replacements.get(target_id)
                    and self.factions[key] == self.factions[target_id]):
                result.append(key)
        return result


def relation_stat_contribution(local_stat, faction):
    # CalcOutputParam 0x3610190; GameConfigParam static doubles at 0x2E8/0x2F0.
    if (type(local_stat) is not int or not -(2**31) <= local_stat < 2**31
            or type(faction) is not int or not -(2**31) <= faction < 2**31):
        raise ValueError('Invalid related character statistic or faction.')
    return math.floor(local_stat * (0.135 if faction == 3 else 0.08))


def equipment_type(category, base_id):
    # EquipmentStatusParam.get_EquipmentType 0x351CDC0.
    if type(category) is not int or type(base_id) is not str:
        raise ValueError('Invalid equipment category or base ID.')
    if not base_id and category == 3:
        return 8
    if category == 4:
        return 10
    for number in range(1,8):
        if f'wp{number:03}' in base_id:
            return number
    return 9 if 'pl' in base_id else 0


class EquipmentLoadoutStats:
    """Resolve only the supplied account's owned equipment into slot totals."""
    def __init__(self, masters, curves):
        masters = list(masters)
        self.stats = EquipmentBaseStats(masters, curves)
        self.types = {row['EquipmentId']:equipment_type(row['Category'],row['BaseId'])
                      for row in masters}

    def character(self, saved_character, owned_equipment):
        owned = {}
        for row in owned_equipment:
            key = row.get('EquipmentId')
            if type(key) is not str or not key or key in owned:
                raise ValueError('Invalid or duplicate owned equipment.')
            owned[key] = row

        def contributions(slot, stat=None):
            values = saved_character.get(slot, [])
            if values is None:
                values = []
            if type(values) is not list:
                raise ValueError('Invalid saved equipment slot.')
            result = []
            for key in values:
                if key is None or key == '':
                    continue
                if type(key) is not str or key not in owned or key not in self.types:
                    raise ValueError('Equipped item is not owned or installed.')
                stats = self.stats.equipment(owned[key])
                kind = self.types[key]
                result.append(stats[stat] if stat else stats['Defense'] if kind == 9
                              else sum(stats.values()) if kind == 8 else stats['Attack'])
            return result

        return {
            'Weapons':equipment_slot_total(contributions('WeaponMain'),contributions('WeaponSub')),
            'Costumes':equipment_slot_total(contributions('Costume'),[]),
            **{'Accessorys'+name:equipment_slot_total(contributions('AccessoryMain',stat),
                contributions('AccessorySub',stat)) for name,stat in
                (('HP','Hp'),('Attack','Attack'),('Defense','Defense'))},
        }


class CharacterCombatStats:
    """Compose local stats and nonrecursive faction totals from account saves."""
    def __init__(self, characters, character_curves, equipment, equipment_curves, buffs):
        characters,equipment = list(characters),list(equipment)
        self.base = CharacterBaseStats(characters,character_curves)
        self.loadouts = EquipmentLoadoutStats(equipment,equipment_curves)
        self.passives = EquipmentPassives(equipment,buffs)
        self.related = RelatedCharacters(characters)

    def power(self, target_id, owned_characters, owned_equipment, ordered_ids, level_overrides=None):
        # CharacterStatusParam.get_Power 0x361081C sums the three totals.
        total = sum(self.character(target_id,owned_characters,owned_equipment,ordered_ids,level_overrides).values())
        if not 0 <= total < 2**31:
            raise ValueError('Character power exceeds native range.')
        return total

    def character(self, target_id, owned_characters, owned_equipment, ordered_ids, level_overrides=None):
        owned_characters,owned_equipment = list(owned_characters),list(owned_equipment)
        related = self.related.select(target_id,ordered_ids,owned_characters)
        rows = {row['CharacterId']:row for row in owned_characters}
        if level_overrides is not None:
            if type(level_overrides) is not dict:
                raise ValueError('Invalid episode level overrides.')
            for key,level in level_overrides.items():
                if (type(key) is not str or key not in rows or type(level) is not int
                        or not 1 <= level < 2**31):
                    raise ValueError('Episode level override is not for an owned character.')
                rows[key] = rows[key] | {'Level':level}
                self.base.character(rows[key])

        def local(key):
            row = rows[key]
            base = self.base.character(row)
            equipment = self.loadouts.character(row,owned_equipment)
            effects = self.passives.character(row,owned_equipment)
            return {
                'Hp':passive_stat(base['Hp'],effects['Hp']) + equipment['AccessorysHP'],
                'Attack':passive_stat(base['Attack'],effects['Attack']) + equipment['Weapons']
                         + equipment['AccessorysAttack'],
                'Defense':passive_stat(base['Defense'],effects['Defense']) + equipment['Costumes']
                          + equipment['AccessorysDefense'],
            }

        result = local(target_id)
        for key in related:
            contribution = local(key)
            for stat in result:
                result[stat] += relation_stat_contribution(contribution[stat],self.related.factions[key])
        if any(not 0 <= value < 2**31 for value in result.values()):
            raise ValueError('Character battle total exceeds native range.')
        return result


def equipment_slot_total(main_values, sub_values):
    """Combine resolved slot contributions using native SubEquipmentCorrection."""
    # GameConfigParam .cctor 0x354F870 stores double 0x3FB999999999999A
    # (0.1). GetEquipmentPower 0x36102E0 applies it after summing subslots.
    totals = []
    for values in (main_values, sub_values):
        if type(values) not in (list, tuple) or any(
                type(value) is not int or not -(2**31) <= value < 2**31
                for value in values):
            raise ValueError('Invalid equipment slot contributions.')
        total = sum(values)
        if not -(2**31) <= total < 2**31:
            raise ValueError('Equipment slot total exceeds native range.')
        totals.append(total)
    result = totals[0] + math.floor(totals[1] * 0.1)
    if not -(2**31) <= result < 2**31:
        raise ValueError('Equipment slot total exceeds native range.')
    return result


def equipment_level_stat(base, scale, levels, saved_level, override_level=0):
    # CalcLevelStatus.Equipment 0x342D37C; equipment scales remain doubles.
    if (type(base) not in (int,float) or not math.isfinite(base)
            or type(scale) not in (int,float) or not math.isfinite(scale)
            or type(saved_level) is not int or not -32768 <= saved_level <= 32767
            or type(override_level) is not int or not -(2**31) <= override_level < 2**31
            or levels is not None and type(levels) not in (list,tuple)):
        raise ValueError('Invalid equipment level parameters.')
    level = override_level if override_level > 0 else saved_level
    if level <= 0 or levels is None:
        return 0
    if not levels:
        raise ValueError('Equipment level curve is empty.')
    growth = levels[min(level,len(levels))-1]
    if type(growth) not in (int,float) or not math.isfinite(growth):
        raise ValueError('Invalid equipment growth value.')
    value = base * (1.0 + scale * growth)
    if not math.isfinite(value):
        raise ValueError('Equipment statistic exceeds native range.')
    # ARM64 FCVTMS rounds down and saturates to signed int32.
    return max(-(2**31),min(2**31-1,math.floor(value)))


class EquipmentBaseStats:
    def __init__(self, masters, curves):
        self.masters = {}
        self.curves = {}
        for row in masters:
            equipment = row.get('EquipmentId')
            if type(equipment) is not str or not equipment or equipment in self.masters:
                raise ValueError('Invalid or duplicate equipment master.')
            self.masters[equipment] = {key:row[key] for key in
                ('Attack','AttackScale','AttackCurve','Defense','DefenseScale','DefenseCurve',
                 'EffectValue','EffectScale','EffectCurve')}
        for row in curves:
            curve,levels = row.get('CurveId'),row.get('Levels')
            if (type(curve) is not str or not curve or curve in self.curves
                    or type(levels) is not list or not levels
                    or any(type(value) not in (int,float) or not math.isfinite(value) for value in levels)):
                raise ValueError('Invalid or duplicate equipment curve.')
            self.curves[curve] = tuple(levels)

    def equipment(self, user_equipment, override_level=0):
        equipment = user_equipment.get('EquipmentId')
        if type(equipment) is not str or equipment not in self.masters:
            raise ValueError('Unknown saved equipment.')
        master = self.masters[equipment]
        result = {}
        for stat,parameter in (('Hp','EffectValue'),('Attack','Attack'),('Defense','Defense')):
            prefix = 'Effect' if stat == 'Hp' else stat
            curve_id = master[prefix+'Curve']
            if type(curve_id) is not str or curve_id and curve_id not in self.curves:
                raise ValueError('Equipment level curve is not installed.')
            result[stat] = equipment_level_stat(master[parameter],master[prefix+'Scale'],
                self.curves.get(curve_id),user_equipment.get('Level'),override_level)
        return result


def character_level_stat(base, scale, levels, level):
    # CalcLevelStatus.Character 0x342D2A4; master scales are float32 values
    # widened to double by CharacterStatusParam.get_HPBase 0x360F72C.
    if (type(base) is not int or not 0 <= base < 2**31
            or type(scale) not in (int,float) or not math.isfinite(scale)
            or type(level) is not int or level < 0
            or type(levels) not in (list,tuple)):
        raise ValueError('Invalid character level parameters.')
    if level == 0:
        return 0
    if level > len(levels):
        raise ValueError('Character level exceeds installed curve.')
    growth = levels[level-1]
    if type(growth) not in (int,float) or not math.isfinite(growth):
        raise ValueError('Invalid character growth value.')
    try:
        native_scale = struct.unpack('<f',struct.pack('<f',scale))[0]
    except (OverflowError,struct.error):
        raise ValueError('Character scale exceeds native range.') from None
    value = base * (1.0 + native_scale * growth)
    if not math.isfinite(value):
        raise ValueError('Character statistic exceeds native range.')
    return math.floor(value)


class CharacterBaseStats:
    def __init__(self, masters, curves):
        self.masters = {}
        self.curves = {}
        for row in masters:
            character = row.get('CharacterId')
            if type(character) is not str or not character or character in self.masters:
                raise ValueError('Invalid or duplicate character master.')
            self.masters[character] = {key:row[key] for stat in ('Hp','Attack','Defense')
                                      for key in (stat,stat+'Scale',stat+'Curve')}
        for row in curves:
            curve = row.get('CurveId')
            levels = row.get('Levels')
            if (type(curve) is not str or not curve or curve in self.curves
                    or type(levels) is not list or not levels
                    or any(type(value) not in (int,float) or not math.isfinite(value) for value in levels)):
                raise ValueError('Invalid or duplicate character level curve.')
            self.curves[curve] = tuple(levels)

    def character(self, user_character):
        character = user_character.get('CharacterId')
        level = user_character.get('Level')
        if type(character) is not str or character not in self.masters or type(level) is not int or level < 1:
            raise ValueError('Unknown character or invalid saved level.')
        master = self.masters[character]
        result = {}
        for stat in ('Hp','Attack','Defense'):
            curve = self.curves.get(master[stat+'Curve'])
            if curve is None:
                raise ValueError('Character level curve is not installed.')
            result[stat] = character_level_stat(master[stat],master[stat+'Scale'],curve,level)
        return result
