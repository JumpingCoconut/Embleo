import sys
import json
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from pve_stats import character_level_stat,CharacterBaseStats,equipment_level_stat,EquipmentBaseStats,equipment_slot_total
from pve_stats import equipment_type,EquipmentLoadoutStats
from pve_stats import relation_stat_contribution
from pve_stats import RelatedCharacters
from pve_stats import passive_effect_value,passive_stat
from pve_stats import EquipmentPassives
from pve_stats import CharacterCombatStats
from pve_stats import AccountCombatStats
from pve_stats import startup_buff_ids, PartyCharacterPresentation


class CharacterStatsTests(unittest.TestCase):
    def test_party_presentation_uses_installed_visuals_and_local_master_id(self):
        entries = [{'Key':'VisualEquipments', 'Value':['costume','weapon']}]
        master = dict(CharacterId='hero', UniqueParamData=json.dumps(
            {'m_Param_StringArray':entries}))
        resolver = PartyCharacterPresentation([master], ['costume','weapon'])
        result = resolver.character('hero')
        self.assertEqual(result, dict(MasterDataId='hero', CharacterName=None,
                                     VisualEquipments=['costume','weapon']))
        result['VisualEquipments'].clear()
        entries[0]['Value'].clear()
        self.assertEqual(resolver.character('hero')['VisualEquipments'], ['costume','weapon'])
        with self.assertRaises(ValueError): resolver.character('unknown')
        with self.assertRaises(ValueError): PartyCharacterPresentation([master], ['costume']).character('hero')
        with self.assertRaises(ValueError): PartyCharacterPresentation([master,master], ['costume','weapon'])
        duplicate = master | {'UniqueParamData':json.dumps({'m_Param_StringArray':[
            {'Key':'VisualEquipments','Value':['costume','weapon']},
            {'Key':'VisualEquipments','Value':['costume','weapon']}]})}
        with self.assertRaises(ValueError): PartyCharacterPresentation([duplicate], ['costume','weapon'])
        padded = master | {'UniqueParamData':json.dumps({'m_Param_StringArray':[
            {'Key':'VisualEquipments','Value':['costume','weapon','','','','']}]})}
        self.assertEqual(PartyCharacterPresentation([padded], ['costume','weapon'])
                         .character('hero')['VisualEquipments'], ['costume','weapon','','','',''])
        missing = master | {'UniqueParamData':'{}'}
        self.assertIsNone(PartyCharacterPresentation([missing], []).character('hero')['VisualEquipments'])

    def test_startup_buff_parameters_require_installed_references(self):
        master = dict(UniqueParamData='{"m_Param_StringArray":[{"Key":"StartUpBuffIdList","Value":["buff"]}]}')
        self.assertEqual(startup_buff_ids(master,{'buff'}),['buff'])
        with self.assertRaises(ValueError): startup_buff_ids(master,set())
        self.assertEqual(startup_buff_ids(dict(UniqueParamData=''),set()),[])
        with self.assertRaises(ValueError): startup_buff_ids(dict(UniqueParamData='[]'),set())

    def test_episode_level_overrides_change_battle_stats_without_save_mutation(self):
        master = dict(CharacterId='self',Faction=1,Hp=100,Attack=20,Defense=10,
                      HpCurve='curve',AttackCurve='curve',DefenseCurve='curve',
                      HpScale=1,AttackScale=1,DefenseScale=1)
        calculator = CharacterCombatStats([master],[dict(CurveId='curve',Levels=[0,1])],[],[],[])
        owned = [dict(CharacterId='self',Level=1,Exp=42)]
        ordered = [dict(Type=1,MasterDataId='self')]
        self.assertEqual(calculator.character('self',owned,[],ordered,{'self':2}),
                         dict(Hp=200,Attack=40,Defense=20))
        self.assertEqual(calculator.power('self',owned,[],ordered,{'self':2}),260)
        provider = AccountCombatStats(calculator,
            lambda account,name:owned if name == 'UserCharacter.json' else [],lambda account:ordered)
        self.assertEqual(provider.character('alice','self',{'self':2}),
                         dict(Hp=200,Attack=40,Defense=20,Power=260))
        self.assertEqual(owned[0],dict(CharacterId='self',Level=1,Exp=42))
        for overrides in ({'unowned':2},{'self':True},{'self':0},{'self':3}):
            with self.assertRaises(ValueError): calculator.character('self',owned,[],ordered,overrides)

    def test_combat_composition_uses_local_related_stats_without_recursion(self):
        master = dict(CharacterId='self',Faction=1,Hp=100,Attack=20,Defense=10,
                      HpCurve='curve',AttackCurve='curve',DefenseCurve='curve',
                      HpScale=0,AttackScale=0,DefenseScale=0)
        calculator = CharacterCombatStats([master,master | dict(CharacterId='related')],
            [dict(CurveId='curve',Levels=[0])],[],[],[])
        owned = [dict(CharacterId=key,Level=1) for key in ('self','related')]
        ordered = [dict(Type=1,MasterDataId=row['CharacterId']) for row in owned]
        self.assertEqual(calculator.character('self',owned,[],ordered),dict(Hp=108,Attack=21,Defense=10))
        self.assertEqual(calculator.power('self',owned,[],ordered),139)
        self.assertEqual(owned[0],dict(CharacterId='self',Level=1))
        calls = []
        def read(account,name):
            calls.append((account,name))
            return owned if account == 'alice' and name == 'UserCharacter.json' else []
        provider = AccountCombatStats(calculator,read,lambda account:ordered if account == 'alice' else [])
        self.assertEqual(provider.character('alice','self'),dict(Hp=108,Attack=21,Defense=10,Power=139))
        self.assertEqual(calls,[('alice','UserCharacter.json'),('alice','UserEquipment.json')])
        with self.assertRaises(ValueError): provider.character('bob','self')

    def test_passives_resolve_main_owned_items_skip_magic_and_subslots(self):
        resolver = EquipmentPassives([dict(EquipmentId='item',Buff=['attack','magic:absent','other'])],
            [dict(ID='attack',EffectType='Setup_Attack',EffectValue=[1.1,1.25]),
             dict(ID='other',EffectType='Status_MaxHP',EffectValue=[2])])
        owned = [dict(EquipmentId='item',SpLevel=2)]
        saved = dict(WeaponMain=['item'],WeaponSub=['unowned'])
        self.assertEqual(resolver.character(saved,owned),dict(Hp=[],Attack=[1.25],Defense=[]))
        with self.assertRaises(ValueError): resolver.character(saved,[])

    def test_passives_add_multiplier_deltas_and_floor_only_final_stat(self):
        self.assertEqual(passive_stat(100,[1.25,1.5]),175)
        self.assertEqual(passive_stat(9,[1.1,1.1]),10)
        self.assertEqual(passive_stat(100,[]),100)
        self.assertEqual(passive_effect_value([1.1,1.2],99),1.2)
        self.assertEqual(passive_effect_value([1.1,1.2],1),1.1)
        self.assertEqual(passive_effect_value([1.1],0),0.0)
        self.assertEqual(passive_effect_value(None,1),0.0)
        with self.assertRaises(ValueError): passive_stat(100,[float('nan')])
        with self.assertRaises(ValueError): passive_effect_value([1.1],True)

    def test_related_characters_use_owned_ordered_same_faction_excluding_self(self):
        masters = [dict(CharacterId=key,Faction=faction,Country=country)
                   for key,faction,country in [('self',1,1),('related',1,2),('other',2,1)]]
        selector = RelatedCharacters(masters)
        owned = [dict(CharacterId=row['CharacterId']) for row in masters]
        ordered = [dict(MasterDataId=key,Type=1) for key in ('other','related','self')]
        ordered.insert(0,dict(MasterDataId='event',Type=3))
        self.assertEqual(selector.select('self',ordered,owned),['related'])
        self.assertEqual(ordered[1]['MasterDataId'],'other')
        with self.assertRaises(ValueError): selector.select('self',ordered,owned[:1])
        with self.assertRaises(ValueError): selector.select('self',ordered+ordered[1:2],owned)
        masters[1]['Faction'] = 2
        self.assertEqual(selector.select('self',ordered,owned),['related'])

    def test_relation_bonus_depends_on_faction_and_rounds_per_character(self):
        self.assertEqual(relation_stat_contribution(100,1),8)
        self.assertEqual(relation_stat_contribution(100,3),13)
        self.assertEqual(sum(relation_stat_contribution(9,1) for _ in range(2)),0)
        self.assertEqual(relation_stat_contribution(-1,3),-1)
        for value,faction in [(True,1),(1,True),(2**31,1)]:
            with self.assertRaises(ValueError): relation_stat_contribution(value,faction)

    def test_replacement_relations_exclude_aliases_and_their_original(self):
        ids = ('base', 'replacement', 'friend', 'friend-alias')
        selector = RelatedCharacters([dict(CharacterId=key, Faction=1) for key in ids])
        owned = [dict(CharacterId=key) for key in ids]
        owned[1]['BaseCharacterId'] = 'base'
        owned[3]['BaseCharacterId'] = 'friend'
        ordered = [dict(MasterDataId=key, Type=1) for key in ids]
        self.assertEqual(selector.select('replacement', ordered, owned), ['friend'])
        self.assertEqual(selector.select('base', ordered, owned), ['friend'])
        self.assertEqual(owned[1], dict(CharacterId='replacement', BaseCharacterId='base'))
        for invalid in ('', 42, False):
            with self.assertRaises(ValueError):
                selector.select('replacement', ordered,
                                [row | {'BaseCharacterId': invalid} if row['CharacterId'] == 'replacement'
                                 else row for row in owned])

    def test_owned_loadout_uses_native_categories_and_subslot_rounding(self):
        master = dict(EquipmentId='weapon',Category=1,BaseId='wp001_base',
                      Attack=19,AttackScale=0,AttackCurve='curve',
                      Defense=7,DefenseScale=0,DefenseCurve='curve',
                      EffectValue=11,EffectScale=0,EffectCurve='curve')
        masters = [master,master | dict(EquipmentId='costume',Category=2,BaseId='pl001'),
                   master | dict(EquipmentId='accessory',Category=3,BaseId='')]
        calculator = EquipmentLoadoutStats(masters,[dict(CurveId='curve',Levels=[0])])
        owned = [dict(EquipmentId=row['EquipmentId'],Level=1) for row in masters]
        saved = dict(WeaponMain=['weapon'],WeaponSub=['weapon','weapon'],Costume=['costume'],
                     AccessoryMain=['accessory'],AccessorySub=['accessory','accessory'])
        self.assertEqual(calculator.character(saved,owned),dict(Weapons=22,Costumes=7,AccessorysHP=13,
                        AccessorysAttack=22,AccessorysDefense=8))
        with self.assertRaises(ValueError): calculator.character(saved,owned[:1])
        self.assertEqual(saved['WeaponSub'],['weapon','weapon'])
        self.assertEqual(equipment_type(4,'wp001'),10)
        self.assertEqual(equipment_type(3,'wp002'),2)
        self.assertEqual(equipment_type(1,'unknown'),0)

    def test_subslots_round_after_summing_and_reject_invalid_contributions(self):
        self.assertEqual(equipment_slot_total([100,20],[9,9]),121)
        self.assertEqual(equipment_slot_total([],[]),0)
        self.assertEqual(equipment_slot_total([10],[-1]),9)
        for main,sub in [([True],[]),([],[1.0]),([2**31-1,1],[])]:
            with self.assertRaises(ValueError): equipment_slot_total(main,sub)

    def test_equipment_clamps_curve_uses_double_scale_and_override(self):
        self.assertEqual(equipment_level_stat(100,0.99999999,[1.0],1),199)
        self.assertEqual(equipment_level_stat(100,0.5,[0.0,1.0],100),150)
        self.assertEqual(equipment_level_stat(100,0.5,[0.0,1.0],1,2),150)
        self.assertEqual(equipment_level_stat(100,0.5,None,1),0)
        self.assertEqual(equipment_level_stat(100,0.5,[1.0],0),0)
        self.assertEqual(equipment_level_stat(2**31,1.0,[1.0],1),2**31-1)
        for args in [(100,True,[1.0],1),(100,1.0,[],1),(100,1.0,[1.0],True)]:
            with self.assertRaises(ValueError): equipment_level_stat(*args)

    def test_equipment_hp_uses_effect_curve_and_preserves_saved_data(self):
        master = dict(EquipmentId='equipment',Attack=20,AttackScale=0.5,AttackCurve='curve',
                      Defense=10,DefenseScale=1.0,DefenseCurve='curve',
                      EffectValue=100,EffectScale=0.25,EffectCurve='curve')
        stats = EquipmentBaseStats([master],[dict(CurveId='curve',Levels=[0.0,1.0])])
        saved = dict(EquipmentId='equipment',Level=2,Unknown=42)
        self.assertEqual(stats.equipment(saved),dict(Hp=125,Attack=30,Defense=20))
        self.assertEqual(saved,dict(EquipmentId='equipment',Level=2,Unknown=42))
    def test_native_index_floor_and_float32_scale(self):
        self.assertEqual(character_level_stat(100,0.5,[0.0,0.25,1.0],2),112)
        self.assertEqual(character_level_stat(100,0.99999999,[1.0],1),200)
        self.assertEqual(character_level_stat(100,1.0,[],0),0)
        for args in [(100,1.0,[1.0],2),(100,True,[1.0],1),
                     (100,1.0,[float('nan')],1),(100,1.0,[1.0],True)]:
            with self.assertRaises(ValueError): character_level_stat(*args)

    def test_saved_level_selects_installed_character_curves_without_mutation(self):
        master = dict(CharacterId='character',Hp=100,HpCurve='hp',HpScale=1.0,
                      Attack=20,AttackCurve='attack',AttackScale=0.5,
                      Defense=10,DefenseCurve='defense',DefenseScale=0.25)
        curves = [dict(CurveId=name,Levels=[0.0,1.0]) for name in ('hp','attack','defense')]
        stats = CharacterBaseStats([master],curves)
        saved = dict(CharacterId='character',Level=2,Exp=42,Unknown='preserved')
        self.assertEqual(stats.character(saved),dict(Hp=200,Attack=30,Defense=12))
        self.assertEqual(saved['Unknown'],'preserved')
        master['Hp'] = 999
        curves[0]['Levels'][1] = 999
        self.assertEqual(stats.character(saved)['Hp'],200)
        with self.assertRaises(ValueError): stats.character(saved | {'Level':3})
        with self.assertRaises(ValueError): stats.character(saved | {'CharacterId':'unknown'})
