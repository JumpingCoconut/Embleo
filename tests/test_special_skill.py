import json
import os
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from combat_debug import apply_instant_mystic_artes, INSTANT_MYSTIC_ENV, GAUGE_BUFF_ID
from scripts.adapt.master_data.special_skill import (
    recover_sequence, sequence_bundle_names, recover_special_skills,
    recover_minion_commands, minion_command_bundle_names,
)
from scripts.adapt.master_data.sequence import adapt_debug_sequence_list
from pve_stats import startup_buff_ids


def timeline(name, clips):
    objects = dict(enumerate(clips, 1))
    sequence = {'m_Name': name, 'tracks': [{'clips': [
        {'behaviourPrefab': {'m_PathID': i}} for i in objects]}]}
    return sequence, lambda ref: objects[ref['m_PathID']]


class SpecialSkillTests(unittest.TestCase):
    def test_minion_command_uses_its_own_index_and_preserves_sacrifice(self):
        command = {'Mode': 2, 'isSetOwnerTarget': 1, 'moveType': 1,
                   'playSequenceName': 'MinionUniqueAttack1', 'isTerminate': 1,
                   'isDisableExceptForLeader': 1}
        seq, resolve = timeline('Charge4', [
            dict(m_Name='Animator Clip', isAttack=1, attackBaseInfo={}),
            dict(m_Name='MinionOrder Clip', clipIndex=0, minionOrderSettings=command)])
        attack = recover_sequence('pl021', seq, resolve)[0]['AttackSetting'][0]
        self.assertEqual(attack['sequenceName'], 'Charge4')
        self.assertEqual(attack['totalClipCount'], 1)
        self.assertEqual(attack['clipDatas'], [{'clip_MinionOrder': command}])

    def test_installed_charles_sacrifice_commands(self):
        root = Path(__file__).resolve().parents[1] / 'src/data'
        manifest_path = root / 'extract/manifest.json'
        if not manifest_path.exists():
            self.skipTest('Local game assets are not installed')
        entries = minion_command_bundle_names(json.loads(manifest_path.read_text(encoding='utf-8')))
        if len(entries) != 2 or not all(
            (root / 'download' / (e['Name'] + '_' + e['Version'] + '.ab')).exists()
            for e in entries
        ):
            self.skipTest('Minion command bundles are not installed')
        rows = recover_minion_commands(root / 'download')
        attacks = {s['sequenceName']: s for r in rows for s in r.get('AttackSetting', [])}
        charge = attacks['Charge4']['clipDatas'][0]['clip_MinionOrder']
        self.assertEqual(charge['playSequenceName'], 'MinionUniqueAttack1')
        self.assertEqual(charge['isTerminate'], 1)
        self.assertEqual(charge['isSetOwnerTarget'], 1)
        self.assertEqual(attacks['Attack4']['clipDatas'][0]['clip_MinionOrder']['playSequenceName'],
                         'MinionUniqueAttack2')

    def test_installed_costume_coverage_and_serialized_keys(self):
        root = Path(__file__).resolve().parents[1] / 'src/data'
        if not (root / 'extract/manifest.json').exists():
            self.skipTest('Local game assets are not installed')
        manifest = json.loads((root / 'extract/manifest.json').read_text(encoding='utf-8'))
        expected = sequence_bundle_names(manifest)
        if not all((root / 'download' / (e['Name'] + '_' + e['Version'] + '.ab')).exists()
                   for e in expected):
            self.skipTest('Special skill bundles are not installed')
        rows = recover_special_skills(root / 'download')
        attacks = [w['AttackSetting'][0] for w in rows if 'AttackSetting' in w]
        self.assertEqual({s['sequenceName'].lower() for s in attacks},
                         {e['Name'].split('/')[-1] for e in expected})
        wire = adapt_debug_sequence_list(rows)
        self.assertEqual(len(wire), len({(r['CharacterId'], r['Category']) for r in wire}))
        for r in wire:
            if r['Category'] == 'ResourceList':
                info = json.loads(r['Data'])['ResourceList']
                self.assertEqual(info['id'], r['CharacterId'])
                self.assertTrue(info['values'])
                continue
            for s in json.loads(r['Data'])[r['Category']]:
                self.assertEqual(s['id'], r['CharacterId'])
                if 'clipDatas' in s:
                    self.assertEqual(s['totalClipCount'], len(s['clipDatas']))

        august = next(r for r in wire if r['CharacterId'] == 'pl010'
                      and r['Category'] == 'ResourceList')
        self.assertIn({'type': 1, 'value': 'External/Effects/SpecialSkill/eff_plsp010_04001shock'},
                      json.loads(august['Data'])['ResourceList']['values'])

    def test_summon_resources_include_circle_and_merge_costumes(self):
        circle = 'External/Effects/SpecialSkill/circle'
        wand = 'External/Effects/SpecialSkill/wand'
        seq, resolve = timeline('SpecialSkill@a', [
            dict(m_Name='Animator Clip', isAttack=1, attackBaseInfo={}),
            dict(m_Name='Summon Clip', clipSettings={'ClipIndex': 0,
                 'BulletEffectSettings': {'PrefabPath': circle},
                 'BulletAttackSettings': {'AttackDamageRate': 7}}, hitSettings={}),
            dict(m_Name='EffectCall Clip', effectSettings=[{'PrefabPath': wand},
                                                         {'PrefabPath': circle}])])
        recovered = recover_sequence('pl010', seq, resolve)
        wire = adapt_debug_sequence_list(recovered + [
            {'ResourceList': [{'id': 'pl010', 'values': [{'type': 1, 'value': circle}]}]}])
        resource = next(r for r in wire if r['Category'] == 'ResourceList')
        self.assertEqual(json.loads(resource['Data']), {'ResourceList': {'id': 'pl010',
                         'values': [{'type': 1, 'value': circle}, {'type': 1, 'value': wand}]}})
        summon = recovered[0]['AttackSetting'][0]['clipDatas'][0]['clip_Summon']
        self.assertEqual(summon['BulletAttackSettings']['AttackDamageRate'], 7)

    def test_sparse_indices_and_costume_keys_preserve_payloads(self):
        clips = [dict(m_Name='Animator Clip', isAttack=1, attackBaseInfo={'SearchDistance': 9}),
                 dict(m_Name='Attack Clip', attackClipSettings={'ClipIndex': 3, 'AttackDamageRate': 7},
                      hitSettings={'HitStopTime': .1}),
                 dict(m_Name='SpecialSkillMagic Clip', clipSettings={'ClipIndex': 2, 'Buffs': []})]
        seq, resolve = timeline('SpecialSkill@costume_a', clips)
        original = deepcopy(clips)
        result = recover_sequence('pl001', seq, resolve)
        attack = result[0]['AttackSetting'][0]
        self.assertEqual(attack['sequenceName'], 'SpecialSkill@costume_a')
        self.assertEqual(attack['totalClipCount'], 4)
        self.assertEqual(attack['clipDatas'][3]['clip_Attack']['AttackDamageRate'], 7)
        self.assertEqual(attack['clipDatas'][:3], [{}, {}, {}])
        self.assertEqual(clips, original)

    def test_shared_indices_keep_first_payload_and_other_families(self):
        seq, resolve = timeline('SpecialSkill@b', [
            dict(m_Name='Animator Clip', isAttack=1, attackBaseInfo={}),
            dict(m_Name='GunAttack Clip', gunAttackClipSettings={'ClipIndex': 0, 'AttackDamageRate': 2}, hitSettings={'x': 1}),
            dict(m_Name='GunAttack Clip', gunAttackClipSettings={'ClipIndex': 0, 'AttackDamageRate': 4}, hitSettings={'x': 2}),
            dict(m_Name='Summon Clip', clipSettings={'ClipIndex': 0, 'BulletAttackSettings': {'AttackDamageRate': 5}}, hitSettings={'x': 3})])
        clip = recover_sequence('pl002', seq, resolve)[0]['AttackSetting'][0]['clipDatas'][0]
        self.assertEqual(clip['clip_Gun']['AttackDamageRate'], 2)
        self.assertEqual(clip['clip_Summon']['BulletAttackSettings']['AttackDamageRate'], 5)
        self.assertEqual(clip['hitSetting'], {'x': 1})

    def test_move_and_update_indices_are_independent(self):
        seq, resolve = timeline('SpecialSkill@c', [
            dict(m_Name='Move Clip', clipIndex=2, direction={'x': 1, 'y': 0, 'z': 0}, speed=3),
            dict(m_Name='UpdateAttackInfo Clip', clipIndex=0, attackBaseInfo={'IsInvincible': 1})])
        rows = recover_sequence('pl003', seq, resolve)
        self.assertEqual(rows[0]['UpdateParameterSetting'][0]['totalClipCount'], 1)
        self.assertEqual(rows[1]['MoveSetting'][0]['speed'], [0, 0, 3])

    def test_unknown_combat_clip_fails_instead_of_dropping_damage(self):
        seq, resolve = timeline('SpecialSkill@d', [dict(m_Name='NewAttack Clip', hitSettings={})])
        with self.assertRaisesRegex(ValueError, 'unsupported combat clip'):
            recover_sequence('pl004', seq, resolve)

    def test_one_owner_category_row_contains_both_costumes(self):
        rows = adapt_debug_sequence_list([
            {'AttackSetting': [{'id': 'pl001', 'sequenceName': 'SpecialSkill@a'}]},
            {'AttackSetting': [{'id': 'pl001', 'sequenceName': 'SpecialSkill@b'}]}])
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(json.loads(rows[0]['Data'])['AttackSetting']), 2)

    def test_manifest_excludes_animation_and_other_sequences(self):
        paths = ['characters/player/pl001/specialskill/a/specialskill@a',
                 'characters/player/pl001/specialskill/a/@a', 'characters/player/pl001/attack']
        rows = [{'Name': name} for name in paths]
        self.assertEqual(sequence_bundle_names({'m_Entries': rows}), rows[:1])

    def test_quick_charge_is_opt_in_preserves_existing_startup_buffs(self):
        group = {'characters': [{'UniqueParamData': json.dumps({'m_Param_StringArray': [
            {'Key': 'StartUpBuffIdList', 'Value': ['existing']}], 'unknown': 9})}],
            'buff': [{'ID': 'existing'}]}
        with patch.dict(os.environ, {INSTANT_MYSTIC_ENV: '0'}):
            self.assertEqual(apply_instant_mystic_artes(deepcopy(group)), group)
        with patch.dict(os.environ, {INSTANT_MYSTIC_ENV: '1'}):
            result = apply_instant_mystic_artes(deepcopy(group))
            apply_instant_mystic_artes(result)
        self.assertEqual(len(result['buff']), 2)
        self.assertEqual(startup_buff_ids(result['characters'][0], {'existing', GAUGE_BUFF_ID}),
                         ['existing', GAUGE_BUFF_ID])
        self.assertEqual(json.loads(result['characters'][0]['UniqueParamData'])['unknown'], 9)
        self.assertEqual(result['buff'][-1]['EffectValue'], [-300.0])
        self.assertNotIn(GAUGE_BUFF_ID, str(group))

    def test_source_switch_or_environment_enables_charging(self):
        from types import SimpleNamespace
        group = {'characters': [], 'buff': []}
        for source, environment in ((False, '0'), (True, '0'), (False, '1'), (True, '1')):
            with self.subTest(source=source, environment=environment), \
                    patch.dict(os.environ, {INSTANT_MYSTIC_ENV: environment}), \
                    patch.dict(sys.modules, {'server': SimpleNamespace(INSTANT_MYSTIC_ARTES=source)}):
                result = apply_instant_mystic_artes(deepcopy(group))
                self.assertEqual(bool(result['buff']), source or environment == '1')
                explicit = apply_instant_mystic_artes(deepcopy(group), enabled=source)
                self.assertEqual(bool(explicit['buff']), source or environment == '1')


if __name__ == '__main__':
    unittest.main()
