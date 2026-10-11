"""Map raid bindings to native episodes, installed scenarios and layouts."""

import json
from copy import deepcopy
from pathlib import Path
from scripts.adapt.adapt_debug_episode_data import fill_episode_layout_group_by_episode_id


GROUPS = {1:'CheckPoints',2:'ArrivalPoints',3:'Kills',4:'Talks',5:'Gimmicks',
          6:'Demos',7:'EditParties',8:'Scripts',9:'PartyFlags',10:'PartyParams',
          11:'RouteForks',12:'RouteMerges',13:'Timers',14:'EnemyParams',
          15:'RouteChecks',16:'PlayerActions',17:'BreakableActions',18:'MiniGames'}


def raid_enemy_detail(layout):
    """Include placed, child and summon-only enemy individuals for battle."""
    ids = []
    for enemy in layout['Enemies']:
        for key in [enemy['EnemyId'], *(enemy.get('Child') or {}).get('Ids', []),
                    (enemy.get('SummonRule') or {}).get('EpisodeEnemyId', '')]:
            if type(key) is not str:
                raise ValueError('Invalid installed raid enemy reference.')
            if key and key not in ids:
                ids.append(key)
    return {'Enemies':[{'EnemyId':key} for key in ids]}


class RaidEpisodeLoader:
    def __init__(self, data_root, definitions):
        self.root = Path(data_root).resolve()
        self.definitions = deepcopy(definitions)

    def _definition(self, identity):
        if type(identity) is not str or identity not in self.definitions:
            raise ValueError('Raid episode is not installed in the catalog.')
        definition = self.definitions[identity]
        if type(definition) is not dict:
            raise ValueError('Invalid installed raid definition.')
        episode_id = definition.get('EpisodeId',identity)
        if type(episode_id) is not str or not episode_id:
            raise ValueError('Canonical native raid episode required.')
        source = self.root / 'extract/masterdata/EpisodeMasterDataObject.json'
        with source.open(encoding='utf-8-sig') as stream:
            episodes = json.load(stream)['Datas']
        if episode_id not in {row['ID'] for row in episodes}:
            raise ValueError('Raid episode must exist in installed native EpisodeInfo data.')
        return definition,episode_id

    def definition_key(self, room):
        binding = room.get('EpisodePveEventId',room['EpisodeId'])
        key = binding if binding in self.definitions else room['EpisodeId']
        _,episode_id = self._definition(key)
        if episode_id != room['EpisodeId']:
            raise ValueError('Raid binding differs from the room native episode.')
        return key

    def visual_settings(self, episode_id):
        """Use checkpoint visual timelines; the native client requires a first row."""
        definition,_ = self._definition(episode_id)
        directory = self.root / 'extract/masterdatadebug/episode'
        layout = (directory / definition['LayoutId']).resolve()
        if layout.parent != directory.resolve():
            raise ValueError('Raid layout must be a direct installed directory.')
        with (layout / 'EpisodeCheckPointMasterDataObject.json').open(encoding='utf-8-sig') as stream:
            entries = json.load(stream)['Datas']
        settings = []
        for entry in entries:
            number, ids = entry['_startScenarioNo'], entry['PartyVisualIds']
            if (type(number) is not int or number < 0 or type(ids) is not list
                    or any(type(value) is not str for value in ids)):
                raise ValueError('Invalid installed raid visual setting.')
            settings.append(dict(ScenarioNo=number, Ids=deepcopy(ids)))
        if not settings:
            raise ValueError('Installed raid visual settings must not be empty.')
        return sorted(settings, key=lambda row: row['ScenarioNo'])

    def __call__(self, episode_id):
        definition,episode_id = self._definition(episode_id)
        location_episode_id = definition.get('LocationEpisodeId',episode_id)
        if type(location_episode_id) is not str or not location_episode_id:
            raise ValueError('Installed episode location identity required.')
        scenario_root = self.root / 'masterdata/scenario'
        path = (scenario_root / (definition['ScenarioId'] + '.json')).resolve()
        if path.parent != scenario_root.resolve():
            raise ValueError('Raid scenario must be a direct installed file.')
        with path.open(encoding='utf-8-sig') as stream:
            entries = json.load(stream)
        if type(entries) is not list or not entries:
            raise ValueError('Installed raid scenario must be a nonempty list.')
        groups = {name:[] for name in GROUPS.values()}
        scenarios = []
        ids, numbers = set(), set()
        for entry in entries:
            if (type(entry) is not dict or type(entry.get('Id')) is not str or not entry['Id']
                    or entry['Id'] in ids or type(entry.get('ScenarioNo')) is not int
                    or not 0 <= entry['ScenarioNo'] < 2**31 or entry['ScenarioNo'] in numbers
                    or type(entry.get('Progress')) is not dict):
                raise ValueError('Invalid or duplicate installed raid scenario.')
            ids.add(entry['Id'])
            numbers.add(entry['ScenarioNo'])
            kind = entry['ProgressType']
            if type(kind) is not int or kind not in GROUPS:
                raise ValueError('Unsupported installed raid scenario kind.')
            groups[GROUPS[kind]].append(deepcopy(entry['Progress']))
            scenarios.append(dict(EpisodeScenarioId=entry['Id'],ScenarioNo=entry['ScenarioNo'],
                                  ProgressType=kind,ProgressId=entry['Id']))
        layout = deepcopy(fill_episode_layout_group_by_episode_id(episode_id, data_root=self.root,
            layout_id=definition['LayoutId'],location_episode_id=location_episode_id))
        overrides = definition.get('EnemyIndividuals',{})
        if type(overrides) is not dict:
            raise ValueError('Invalid configured raid enemy individuals.')
        if overrides:
            with (self.root/'masterdata/EnemyIndividualMasterData.json').open(encoding='utf-8-sig') as stream:
                individuals = json.load(stream)
            installed = {row['Index'] for row in individuals}
            roots = {row['EpisodeEnemyId']:row for row in layout['Enemies']}
            if len(roots) != len(layout['Enemies']):
                raise ValueError('Duplicate configured enemy spawn identity.')
            for spawn,individual in overrides.items():
                if (type(spawn) is not str or spawn not in roots
                        or type(individual) is not str or individual not in installed):
                    raise ValueError('Configured enemy must resolve to an installed spawn and individual.')
                roots[spawn]['EnemyId'] = individual
        return dict(EpisodeDetail=dict(Scenarios=scenarios, LayoutGroup=layout,
                                      ScenarioGroup=groups, EventDrops=deepcopy(definition['EventDrops'])),
                    EnemyDetail=raid_enemy_detail(layout),
                    EpisodeDetailUser=deepcopy(definition['EpisodeDetailUser']),
                    LimitTime=definition['LimitTime'], BgmId=definition['BgmId'])
