import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from pve_setup import installed_runtime_factory
from pve_preparation import BattleAssembler


class SetupTests(unittest.IsolatedAsyncioTestCase):
    async def test_factory_wires_catalog_account_providers_and_installed_battle_policy(self):
        catalog = SimpleNamespace(episodes=SimpleNamespace(links=[{'EpisodeId':'raid','EpisodePveEventId':'link'}]),
                                  eligible_event=Mock())
        reader = lambda account:dict(Power=99999,Platform='android',ClientVersion='1.6.0')
        arguments = dict(eligibility_provider=reader,room_settings_provider=reader,
                         room_view_provider=reader,player_provider=reader,connection_provider=reader)
        responses = Mock()
        assembler = BattleAssembler(None,None,responses)
        with patch('pve_setup.installed_battle_assembler',return_value=assembler) as build:
            factory = installed_runtime_factory(2,'installed','database',reader,
                {'raid':{}},{},catalog,**arguments)
            build.assert_called_once()
        responses.for_room.assert_called_once_with({'EpisodeId':'raid','BattleId':'preflight'})
        prepared = SimpleNamespace(account_id='alice',character=Mock(return_value={'Power':100}))
        assembler.eligibility_validator({'EpisodeId':'raid'},prepared,'selected',None)
        catalog.eligible_event.assert_called_once_with('raid',100,'android','1.6.0')
        prepared.character.assert_called_once_with('alice','selected',None)
        catalog.eligible_event.side_effect = ValueError('Event expired')
        with self.assertRaisesRegex(ValueError,'Event expired'):
            assembler.eligibility_validator({'EpisodeId':'raid'},prepared,'selected',None)
        runtime = factory()
        self.assertIs(runtime.service.event_catalog,catalog)
        self.assertIs(runtime.service.battle_provider,assembler)
        self.assertIs(runtime.service.battle_enemy_provider,assembler.enemy_spawns)
        self.assertIs(runtime.service.player_provider,reader)
        await runtime.stop()
        responses.for_room.side_effect = ValueError('Missing installed layout')
        with patch('pve_setup.installed_battle_assembler',return_value=assembler):
            with self.assertRaisesRegex(ValueError,'Missing installed layout'):
                installed_runtime_factory(2,'installed','database',reader,
                    {'raid':{}},{},catalog,**arguments)
        for definitions in ({},{'other':{}},{'raid':{},'other':{}}):
            with self.assertRaises(ValueError):
                installed_runtime_factory(2,'installed','database',reader,
                    definitions,{},catalog,**arguments)
