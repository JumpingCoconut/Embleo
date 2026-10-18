from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from scripts.adapt.sequence_data.adapt_sequence import adapt_sequence_timeline, serialize_setting
from scripts.adapt.sequence_data.tracks.Attack import adapt_attack_track


def clip(name, **values):
    return {'behaviour': dict(m_Name=name, **values)}


def track(name, clips):
    return {'behaviour': {'m_Name': name}, 'clips': clips, 'keys': []}


class SequenceProjectileTests(unittest.TestCase):
    def test_lucien_charge_combines_melee_and_projectile_tracks(self):
        timeline = {'action_name': 'Charge5', 'tracks': [
            track('Animator Track', [clip('Animator Clip', isAttack=1, attackBaseInfo={'SearchDistance': 9})]),
            track('Attack Track', [clip('Attack Clip', attackClipSettings={'ClipIndex': 0}, hitSettings={})]),
            track('Attack Track', [clip('GunAttack Clip', gunAttackClipSettings={
                'ClipIndex': index, 'BulletEffectSettings': {'PrefabPath': 'External/Effects/projectile'}},
                hitSettings={}) for index in range(1, 7)])]}
        original = deepcopy(timeline)
        adapted = adapt_sequence_timeline(timeline, 'pl005')
        row = adapted['AttackSetting']
        self.assertEqual(row['totalClipCount'], 7)
        self.assertIn('clip_Attack', row['clipDatas'][0])
        for index in range(1, 7):
            self.assertEqual(row['clipDatas'][index]['clip_Gun']['ClipIndex'], index)
        self.assertEqual(row['baseInfo'], {'SearchDistance': 9})
        self.assertIn({'type': 1, 'value': 'External/Effects/projectile'}, adapted['ResourceList']['values'])
        self.assertEqual(timeline, original)

    def test_repeated_projectile_shots_keep_first_settings_at_shared_index(self):
        clips = [clip('GunAttack Clip', gunAttackClipSettings={'ClipIndex': index, 'LifeTime': life},
                      hitSettings={'value': life}) for index, life in [(2, 1), (2, 9), (0, 3)]]
        row = adapt_attack_track({'clips': clips}, 'Attack2', 'pl005')
        self.assertEqual(row['totalClipCount'], 3)
        self.assertEqual(row['clipDatas'][1], {})
        self.assertEqual(row['clipDatas'][2]['clip_Gun']['LifeTime'], 1)
        self.assertEqual(row['clipDatas'][2]['hitSetting'], {'value': 1})

    def test_distinct_families_can_share_one_slot(self):
        row = adapt_attack_track({'clips': [
            clip('GunAttack Clip', gunAttackClipSettings={'ClipIndex': 0}),
            clip('Summon Clip', clipSettings={'ClipIndex': 0})]}, 'Skill', 'pl001')
        self.assertEqual(row['totalClipCount'], 1)
        self.assertIn('clip_Gun', row['clipDatas'][0])
        self.assertIn('clip_Summon', row['clipDatas'][0])

    def test_implicit_enemy_indices_are_still_sequential(self):
        row = adapt_attack_track({'clips': [clip('EnemyAttack Clip', _hitParameter={'DamageRate': value})
                                           for value in (2, 3)]}, 'Attack', 'em0001')
        self.assertEqual(row['totalClipCount'], 2)
        self.assertEqual([slot['enemy_Hit']['DamageRate'] for slot in row['clipDatas']], [2, 3])

    def test_invalid_serialized_index_is_rejected(self):
        for index in (-1, 4096, True):
            with self.subTest(index=index), self.assertRaises(ValueError):
                adapt_attack_track({'clips': [clip('Attack Clip', attackClipSettings={'ClipIndex': index})]}, 'Attack', 'pl005')

    def test_resource_wrapper_is_one_deduplicated_object(self):
        timeline = {'action_name': 'Skill', 'tracks': [
            track('EffectCall Track', [clip('EffectCall Clip', effectSettings=[{'PrefabPath': 'External/Effects/test'}])]),
            track('Sound Track', [clip('VoiceCall Clip', soundKey='Skill', soundKeyList=['Skill']),
                                  clip('SoundCall Clip', soundKey='se001')])]}
        resources = adapt_sequence_timeline(timeline, 'pl005')['ResourceList']
        expected = {'id': 'pl005', 'values': [{'type': 1, 'value': 'External/Effects/test'},
                    {'type': 30, 'value': 'Skill'}, {'type': 10, 'value': 'se001'}]}
        self.assertEqual(json.loads(serialize_setting('ResourceList', 'pl005', [resources, resources])),
                         {'ResourceList': expected})
        self.assertEqual(json.loads(serialize_setting('ResourceList', 'em0001', [resources]))['ResourceList']['id'],
                         'em0001')
        self.assertEqual(json.loads(serialize_setting('AttackSetting', 'pl005', [{'sequenceName': 'Attack'}])),
                         {'AttackSetting': [{'sequenceName': 'Attack'}]})

    def test_lydie_projectile_and_explosion_settings_and_resources_are_preserved(self):
        settings = {'ClipIndex': 0, 'Offset': {'x': 0, 'y': 1, 'z': 2},
                    'IgnoreHitLayer': {'m_Bits': 8192},
                    'FinishEffectSettings': {'PrefabPath': 'External/Effects/explosion',
                                             'Offset': {'x': 0, 'y': 0, 'z': 3}}}
        timeline = {'action_name': 'Attack3', 'tracks': [
            track('Attack Track', [clip('Grenade PlungingFireAttack Clip', gunAttackClipSettings=settings)]),
            track('EffectCall Track', [clip('EffectCall Clip', effectSettings=[
                {'PrefabPath': 'External/Effects/gun'}])])]}
        original = deepcopy(timeline)
        adapted = adapt_sequence_timeline(timeline, 'pl020')
        projectile = adapted['AttackSetting']['clipDatas'][0]['clip_Plunging']
        self.assertEqual(projectile['Offset'], settings['Offset'])
        self.assertEqual(projectile['FinishEffectSettings'], settings['FinishEffectSettings'])
        self.assertEqual(projectile['IgnoreHitLayer'], {'m_Mask': 8192})
        resources = json.loads(serialize_setting('ResourceList', 'pl020', [adapted['ResourceList']]))['ResourceList']
        self.assertEqual(resources, {'id': 'pl020', 'values': [
            {'type': 1, 'value': 'External/Effects/explosion'}, {'type': 1, 'value': 'External/Effects/gun'}]})
        self.assertEqual(timeline, original)


if __name__ == '__main__':
    unittest.main()
