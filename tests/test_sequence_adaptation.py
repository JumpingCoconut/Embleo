from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from scripts.adapt.sequence_data.adapt_sequence import adapt_sequence_timeline, serialize_setting, get_sequence_timeline_data
from scripts.adapt.sequence_data.tracks.Attack import adapt_attack_track
from scripts.adapt.sequence_data.tracks.UpdateParameter import adapt_update_parameter_track
from scripts.adapt.master_data.sequence import merge_sequence_masters
from scripts.adapt.extract_sequence_data import installed_bundle_paths
import tempfile


def clip(name, **values):
    return {'behaviour': dict(m_Name=name, **values)}


def track(name, clips):
    return {'behaviour': {'m_Name': name}, 'clips': clips, 'keys': []}


class SequenceAdaptationTests(unittest.TestCase):
    def test_asset_summon_keeps_healing_index_one(self):
        data = {'ClipIndex': 1, 'BulletKind': 2,
                'BulletAttackSettings': {'IgnoreHitLayer': {'m_Bits': 0x80002000}}}
        source = {'clips': [clip('Summon Clip', clipSettings=data, hitSettings={})]}
        original = deepcopy(source)
        row = adapt_attack_track(source, 'Attack2', 'pl009')
        self.assertEqual(row['totalClipCount'], 2)
        self.assertEqual(row['clipDatas'][0], {})
        self.assertEqual(row['clipDatas'][1]['clip_Summon']['ClipIndex'], 1)
        self.assertEqual(row['clipDatas'][1]['clip_Summon']['BulletAttackSettings']['IgnoreHitLayer'],
                         {'m_Mask': -2147475456})
        self.assertEqual(source, original)

    def test_repeated_shots_share_first_payload_without_renumbering(self):
        clips = [clip('GunAttack Clip', gunAttackClipSettings={'ClipIndex': i, 'LifeTime': lifetime},
                      hitSettings={'value': lifetime}) for i, lifetime in [(2, 1), (2, 9), (0, 3)]]
        row = adapt_attack_track({'clips': clips}, 'Attack2', 'pl005')
        self.assertEqual(row['totalClipCount'], 3)
        self.assertEqual(row['clipDatas'][1], {})
        self.assertEqual(row['clipDatas'][2]['clip_Gun']['LifeTime'], 1)
        self.assertEqual(row['clipDatas'][2]['hitSetting'], {'value': 1})

    def test_multiple_attack_tracks_merge_distinct_slots_and_families(self):
        timeline = {'action_name': 'SpecialSkill@a', 'tracks': [
            track('Animator Track', [clip('Animator Clip', isAttack=1, attackBaseInfo={'SearchDistance': 9})]),
            track('Attack Track', [clip('GunAttack Clip', gunAttackClipSettings={'ClipIndex': 0}, hitSettings={})]),
            track('Attack Track', [clip('Summon Clip', clipSettings={'ClipIndex': 0}, hitSettings={}),
                                   clip('Attack Clip', attackClipSettings={'ClipIndex': 2}, hitSettings={})])]}
        row = adapt_sequence_timeline(timeline, 'pl001')['AttackSetting']
        self.assertEqual(row['totalClipCount'], 3)
        self.assertIn('clip_Gun', row['clipDatas'][0])
        self.assertIn('clip_Summon', row['clipDatas'][0])
        self.assertIn('clip_Attack', row['clipDatas'][2])
        self.assertEqual(row['baseInfo'], {'SearchDistance': 9})

    def test_implicit_enemy_indices_span_multiple_move_tracks(self):
        timeline = {'action_name': 'Walk', 'tracks': [track('Move Track', [
            clip('EnemyMove Clip', direction={'z': 1}, speed=s)]) for s in (1, 2)]}
        row = adapt_sequence_timeline(timeline, 'enemy')['MoveSetting']
        self.assertEqual(row['speed'], [1, 2])
        self.assertEqual(row['moveCount'], [0, 1])

    def test_update_indices_and_families_remain_independent(self):
        row = adapt_update_parameter_track({'clips': [
            clip('SpecialSkillMagic Clip', clipSettings={'ClipIndex': 2}),
            clip('UpdateAttackInfo Clip', clipIndex=0, attackBaseInfo={'IsInvincible': 1})]}, 'Skill', 'pl001')
        self.assertEqual(row['totalClipCount'], 3)
        self.assertEqual(row['clipDatas'][1], {})
        self.assertEqual(row['clipDatas'][2], {'clip_SpecialSkillMagic': {'ClipIndex': 2}})
        self.assertEqual(row['clipDatas'][0], {'attackBaseInfo': {'IsInvincible': 1}})

    def test_resources_cover_effect_sound_and_voice_tracks_as_one_object(self):
        timeline = {'action_name': 'Skill', 'tracks': [
            track('Effect Track', [clip('EffectCall Clip', effectSettings=[{'PrefabPath': 'External/Effects/test'}])]),
            track('Sound Track', [clip('VoiceCall Clip', soundKey='Skill', soundKeyList=['Skill']),
                                  clip('SoundCall Clip', soundKey='se001')])]}
        resources = adapt_sequence_timeline(timeline, 'pl001')['ResourceList']
        result = json.loads(serialize_setting('ResourceList', 'pl001', [resources, resources]))['ResourceList']
        self.assertEqual(result, {'id': 'pl001', 'values': [
            {'type': 1, 'value': 'External/Effects/test'}, {'type': 30, 'value': 'Skill'},
            {'type': 10, 'value': 'se001'}]})

    def test_asset_merge_unions_resources_and_retains_unknown_fields(self):
        def row(values):
            return dict(CharacterId='pl001', Category='ResourceList', Data=json.dumps({'ResourceList': values}))
        a = row({'id': 'pl001', 'unknown': 4, 'values': [{'type': 1, 'value': 'old'}]})
        b = row({'id': 'pl001', 'values': [{'type': 1, 'value': 'old'}, {'type': 1, 'value': 'new'}]})
        result = merge_sequence_masters([a], [b], 'CharacterId')
        value = json.loads(result[0]['Data'])['ResourceList']
        self.assertEqual(value['unknown'], 4)
        self.assertEqual([r['value'] for r in value['values']], ['old', 'new'])

    def test_invalid_indices_fail_before_generating_unusable_masters(self):
        for index in (-1, 4096, True):
            with self.subTest(index=index), self.assertRaises(ValueError):
                adapt_attack_track({'clips': [clip('Attack Clip', attackClipSettings={'ClipIndex': index})]}, 'Attack', 'pl001')

    def test_missing_asset_base_does_not_erase_existing_combat_defaults(self):
        def row(entry):
            return dict(EnemyId='enemy', Category='AttackSetting', Data=json.dumps({'AttackSetting': [entry]}))
        old = row(dict(sequenceName='Attack', baseInfo={'SearchDistance': 9}, clipDatas=[{'old': 1}]))
        new = row(dict(sequenceName='Attack', baseInfo=None, clipDatas=[{'enemy_Hit': {'DamageRate': 3}}]))
        result = merge_sequence_masters([old], [new], 'EnemyId')
        entry = json.loads(result[0]['Data'])['AttackSetting'][0]
        self.assertEqual(entry['baseInfo'], {'SearchDistance': 9})
        self.assertEqual(entry['clipDatas'], [{'enemy_Hit': {'DamageRate': 3}}])

    def test_manifest_selection_ignores_retained_old_bundle_versions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root/'download/characters/player/pl009/sequences'
            folder.mkdir(parents=True)
            (root/'extract').mkdir()
            for version in ('new', 'old'):
                (folder/f'attack2_{version}.ab').touch()
            (root/'extract/manifest.json').write_text(json.dumps({'m_Entries': [
                {'Name': 'characters/player/pl009/sequences/attack2', 'Version': 'new'}]}))
            paths = installed_bundle_paths(root/'download/characters', 'player/pl009/sequences/*.ab')
            self.assertEqual(paths, [folder/'attack2_new.ab'])
            (folder/'attack2_new.ab').unlink()
            with self.assertRaisesRegex(FileNotFoundError, 'rerun setup'):
                installed_bundle_paths(root/'download/characters', 'player/pl009/sequences/*.ab')

    def test_null_timeline_reference_does_not_emit_empty_replacement(self):
        from types import SimpleNamespace
        self.assertEqual(get_sequence_timeline_data(SimpleNamespace(objects=[]), 0, 'Attack', 'enemy'), {})

    def test_installed_assets_retain_healing_and_costume_summon_settings(self):
        from scripts.adapt.master_data.healing_circle import healing_circle_bundle_names
        from scripts.adapt.master_data.special_skill import sequence_bundle_names, recover_bundle
        import UnityPy
        root = Path(__file__).resolve().parents[1] / 'src/data'
        if not (root/'extract/manifest.json').is_file():
            self.skipTest('Local game assets are not installed')
        manifest = json.loads((root/'extract/manifest.json').read_text(encoding='utf-8-sig'))
        entries = healing_circle_bundle_names(manifest) + [e for e in sequence_bundle_names(manifest)
                   if e['Name'].startswith('characters/player/pl010/')]
        paths = [(e, root/'download'/(e['Name']+'_'+e['Version']+'.ab')) for e in entries]
        if not entries or any(not p.is_file() for e, p in paths):
            self.skipTest('Healing and costume sequence bundles are not installed')
        for entry, path in paths:
            with self.subTest(sequence=entry['Name']):
                owner = entry['Name'].split('/')[2]
                reference = next(r['AttackSetting'][0] for r in recover_bundle(path, owner) if 'AttackSetting' in r)
                env = UnityPy.load(str(path))
                timeline = get_sequence_timeline_data(env, '', reference['sequenceName'], owner)
                actual = adapt_sequence_timeline(timeline, owner)['AttackSetting']
                self.assertEqual(actual['totalClipCount'], reference['totalClipCount'])
                self.assertEqual(actual['baseInfo'], reference['baseInfo'])
                # The complete upstream adapter additionally recovers buff clips.
                for index, expected in enumerate(reference['clipDatas']):
                    for family, settings in expected.items():
                        from scripts.adapt.sequence_data.tracks.Attack import normalize_IgnoreHitLayer
                        self.assertEqual(actual['clipDatas'][index][family], normalize_IgnoreHitLayer(settings))


if __name__ == '__main__':
    unittest.main()
