import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from pve_players import SnapshotRaidPlayers
from pve_stats import PreparedCombatStats, PartyCharacterPresentation


class PlayerTests(unittest.TestCase):
    def test_profile_and_eligibility_use_same_owned_snapshot(self):
        class Calculator:
            def character(self,*args): return dict(Hp=100,Attack=20,Defense=10)
        class Snapshots:
            calls = []
            def prepare(self,account):
                self.calls.append(account)
                return PreparedCombatStats(Calculator(),account,{
                    'User.json':dict(id=account,name=account),
                    'UserCharacter.json':[dict(CharacterId='hero',Level=2,Exp=42,
                                              VisualEquipment=['costume','weapon'])],
                    'UserEquipment.json':[]},[])
        snapshots = Snapshots()
        presentation = PartyCharacterPresentation([dict(CharacterId='hero',UniqueParamData='{}')],
                                                  ['costume','weapon'])
        provider = SnapshotRaidPlayers(snapshots,presentation,
            lambda account,prepared:dict(CharacterId='hero',Platform='android',
                                        ClientVersion='1.6.0',MissionRank=0))
        player,eligibility = provider.read('alice')
        self.assertEqual(snapshots.calls,['alice'])
        self.assertEqual((player['UserId'],player['Name'],player['CharacterLevel']),('alice','alice',2))
        self.assertEqual(eligibility,dict(Power=130,Platform='android',ClientVersion='1.6.0'))
        self.assertEqual(player['CharacterPower'],eligibility['Power'])
        self.assertEqual(provider.player('bob')['UserId'],'bob')
        admission = provider.admission('alice')
        self.assertEqual((admission['CharacterId'],admission['CharacterHp'],admission['Ready']),('',0,0))
        self.assertEqual(provider.admission_eligibility('alice')['Power'],130)
        self.assertEqual(provider.for_character('alice','hero')['CharacterId'],'hero')
        with self.assertRaises(ValueError): provider.for_character('alice','unowned')
