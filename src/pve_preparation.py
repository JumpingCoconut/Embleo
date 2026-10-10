"""Assemble paired raid fields from one account snapshot per participant."""

from copy import deepcopy
import secrets
import json
from pathlib import Path
from prizm_rooms import BattlePreparation


def prepared_enemy_spawns(account, room):
    """Authorize host-created layout enemies from the frozen start response."""
    players = room.get('Players', [])
    members = [player for player in players if player.get('UserId') == account]
    if len(members) != 1 or members[0].get('IsHost') is not True:
        return frozenset()
    responses = room.get('PreparedBattle')
    if type(responses) is not dict or account not in responses:
        raise ValueError('Prepared raid response required for enemy spawning.')
    layout = responses[account]['EpisodeDetail']['LayoutGroup']['Enemies']
    if type(layout) is not list:
        raise ValueError('Invalid prepared enemy layout.')
    allowed = set()
    for row in layout:
        key = row.get('EpisodeEnemyId') if type(row) is dict else None
        if type(key) is not str or not key or key in allowed:
            raise ValueError('Invalid or duplicate enemy construction identity.')
        allowed.add(key)
    return frozenset(allowed)


class PreparedEnemySpawns:
    """Validate native construction identities against frozen individual links."""
    def __call__(self, account, room):
        return prepared_enemy_spawns(account, room)

    def authorize(self, account, room, unique_id):
        roots = prepared_enemy_spawns(account, room)
        if not roots or type(unique_id) is not str or len(unique_id) > 512:
            return False
        response = room['PreparedBattle'][account]
        layout = response['EpisodeDetail']['LayoutGroup']['Enemies']
        root_individuals = {row['EpisodeEnemyId']:row['EnemyId'] for row in layout}
        root_children = {row['EpisodeEnemyId']:(row.get('Child') or {}).get('Ids', []) for row in layout}
        individuals = {}
        for row in response['MasterGroup']['enemyIndividuals']:
            key = row.get('Index') if type(row) is dict else None
            if (type(key) is not str or not key or key in individuals
                    or any(separator in key for separator in ('/', '+', '.'))):
                raise ValueError('Invalid enemy individual identity.')
            individuals[key] = row

        def resolve(identity, depth):
            if identity in root_individuals:
                key = root_individuals[identity]
                children = root_children[identity]
                if type(children) is not list or any(type(key) is not str for key in children):
                    raise ValueError('Invalid child enemy links.')
                return (key, children) if key in individuals else None
            if depth >= 32 or not identity.startswith('Ext.'):
                return None
            expression = identity[4:]
            boundary = max(expression.rfind('/'), expression.rfind('+'), expression.rfind('.'))
            if boundary <= 0:
                return None
            source, operator, target = expression[:boundary], expression[boundary], expression[boundary+1:]
            if target not in individuals:
                return None
            resolved_source = resolve(source, depth + 1)
            if resolved_source is None:
                return None
            source_id, children = resolved_source
            row = individuals[source_id]
            if operator == '/':
                condition = row.get('TransformConditions', 0)
                valid = (type(condition) is int and condition != 0 and row.get('TransformId') == target)
            elif operator == '+':
                summons = row.get('SummonEnemyIndividualIds', [])
                valid = type(summons) is list and target in summons
            else:
                valid = target in children
            return (target, children if operator == '/' else []) if valid else None

        return resolve(unique_id, 0) is not None


def installed_battle_assembler(data_root, database, ordering, definitions,
                               base_visuals, master_group=None, extra_saves=(),
                               level_overrides=None):
    """Build the battle provider from the setup pipeline's installed masters.

    ordering derives party priority from the account snapshot. Definitions are
    explicitly catalog-authorized raid mappings, not network request fields.
    """
    from pve_stats import CharacterCombatStats, SnapshotCombatStats, PartyCharacterPresentation
    from pve_episode import RaidEpisodeLoader
    root = Path(data_root).resolve()
    def load(name):
        with (root / 'masterdata' / name).open(encoding='utf-8-sig') as stream:
            return json.load(stream)
    characters = load('CharacterMasterData.json')
    equipment = load('EquipmentMasterData.json')
    character_curves = load('TemporaryLevelStatusCurveCharacterMasterData.json')
    equipment_curves = load('TemporaryLevelStatusCurveEquipmentMasterData.json')
    buffs = load('BuffMasterData.json')
    calculator = CharacterCombatStats(characters, character_curves, equipment,
                                      equipment_curves, buffs)
    group = {key:[] for key in ('searchMoveArounds','characterLevelExp',
        'characterBehaviourTrees','enemyBehabiourTrees','secretMissions',
        'tutorialGuides','equipmentSpLevelExp')}
    group.update(deepcopy(master_group or {}))
    for key,name in (('enemies','EnemyMasterData.json'),
                     ('enemyIndividuals','EnemyIndividualMasterData.json'),
                     ('partsStatusInfos','PartsStatusInfo.json'),('items','ItemMasterData.json'),
                     ('characterSequences','CharacterSequenceMasterData.json'),
                     ('enemySequences','EnemySequenceMasterData.json'),('vehicles','VehicleMasterData.json')):
        group[key] = load(name)
    group.update(characters=deepcopy(characters),equipments=deepcopy(equipment),
                 characterLevelStatus=deepcopy(character_curves),
                 equipmentLevelStatus=deepcopy(equipment_curves),buff=deepcopy(buffs))
    snapshots = SnapshotCombatStats(calculator,database,ordering,
                                   tuple(dict.fromkeys(('UserItems.json',*extra_saves))))
    presentation = PartyCharacterPresentation(characters,[row['EquipmentId'] for row in equipment],equipment)
    responses = InstalledBattleResponses(characters,base_visuals,group,
                                         RaidEpisodeLoader(root,definitions))
    return BattleAssembler(snapshots,presentation,responses,level_overrides)


class BattleAssembler:
    """response_builder owns installed episode details and member tokens.

    It receives the detached room, account snapshot and selected PlayCharacter.
    It must only construct data, without writing saves or publishing tokens.
    Rooms validates the complete responses before freezing any battle state.
    """
    def __init__(self, snapshots, presentation, response_builder, level_overrides=None):
        self.snapshots = snapshots
        self.presentation = presentation
        self.response_builder = response_builder
        self.level_overrides = level_overrides
        self.enemy_spawns = PreparedEnemySpawns()
        self.eligibility_validator = None

    def __call__(self, room):
        room = deepcopy(room)
        room['BattleId'] = secrets.token_hex(16)
        builder = (self.response_builder.for_room(deepcopy(room))
                   if hasattr(self.response_builder, 'for_room') else self.response_builder)
        responses, characters, identities = {}, {}, {}
        for player in room['Players']:
            account = player['UserId']
            if account in responses:
                raise ValueError('Duplicate battle participant.')
            prepared = self.snapshots.prepare(account)
            character_id = player['CharacterId']
            selected_id = character_id
            if hasattr(self.presentation, 'party_id'):
                character_id = prepared.party_character(character_id, self.presentation)
            overrides = (self.level_overrides(deepcopy(room), prepared)
                         if self.level_overrides else None)
            if overrides is not None and character_id != selected_id and selected_id in overrides:
                overrides = deepcopy(overrides) | {character_id:overrides[selected_id]}
            if self.eligibility_validator is not None:
                self.eligibility_validator(deepcopy(room),prepared,character_id,overrides)
            paired = prepared.battle_character(account, character_id,
                self.presentation.character(character_id), overrides)
            response = deepcopy(builder(deepcopy(room), prepared,
                                                     deepcopy(paired['PlayCharacter'])))
            detail = response['EpisodeDetailUser']
            detail['playCharacters'] = [deepcopy(paired['PlayCharacter'])]
            responses[account] = response
            characters[account] = paired['CharacterData']
            identities[account] = (selected_id, character_id)
        return BattlePreparation(responses, characters, identities)


class InstalledBattleResponses:
    """Compose account-scoped start data from installed episode definitions.

    episode_loader accepts a catalog-authorized episode ID and returns its
    EnemyDetail, EpisodeDetail, EpisodeDetailUser, LimitTime and BgmId.
    The EpisodeDetailUser definition supplies fresh-run defaults, never another
    account's checkpoint/playlog. Items must be included in the frozen snapshot.
    """
    def __init__(self, character_masters, base_visuals, master_group, episode_loader):
        self.characters = deepcopy(character_masters)
        self.visuals = deepcopy(base_visuals)
        self.master_group = deepcopy(master_group)
        self.episode_loader = episode_loader

    def __call__(self, room, prepared, play):
        return self.for_room(room)(room, prepared, play)

    def for_room(self, room):
        """Load the installed episode once, before preparing any participants."""
        installed = deepcopy(self.episode_loader(room['EpisodeId']))
        if (type(installed) is not dict
                or set(installed) != {'EnemyDetail','EpisodeDetail','EpisodeDetailUser','LimitTime','BgmId'}
                or any(type(installed[key]) is not dict for key in
                       ('EnemyDetail','EpisodeDetail','EpisodeDetailUser'))
                or type(installed['LimitTime']) is not int or not 0 <= installed['LimitTime'] < 2**31
                or type(installed['BgmId']) is not str):
            raise ValueError('Complete installed raid definition required.')
        identity = (room['EpisodeId'], room['BattleId'])
        def build(context, prepared, play):
            if (context['EpisodeId'], context['BattleId']) != identity:
                raise ValueError('Episode preparation belongs to another battle.')
            return self._build(context, prepared, play, deepcopy(installed))
        return build

    def _build(self, room, prepared, play, installed):
        account = prepared.account_id
        character_detail = {
            'characters':deepcopy(self.characters),
            'userCharacters':prepared.save(account,'UserCharacter.json'),
            'userEquipments':prepared.save(account,'UserEquipment.json'),
            'userItems':prepared.save(account,'UserItems.json'),
            'baseVisual':deepcopy(self.visuals),
        }
        installed['EpisodeDetailUser']['playCharacters'] = [deepcopy(play)]
        return installed | {'EpisodeToken':secrets.token_hex(32),
                            'BattleId':room['BattleId'],
                            'CharacterDetail':character_detail,
                            'MasterGroup':deepcopy(self.master_group)}
