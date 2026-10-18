import json
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from scripts.adapt.master_data.healing_circle import (
    HEALING_CIRCLE_SEQUENCES, healing_circle_bundle_names,
    recover_healing_circles, replace_recovered_attacks,
)
from scripts.adapt.master_data.sequence import adapt_debug_sequences_master_data
from scripts.adapt.master_data.special_skill import recover_sequence


class HealingCircleTests(unittest.TestCase):
    def recovered(self, name):
        settings = {'ClipIndex': 1, 'BulletKind': 2, 'LifeTime': 18,
                    'BulletAttackSettings': {'IgnoreHitLayer': {'m_Bits': 0x80002000}},
                    'FinishEffectSettings': {'PrefabPath': ''}}
        clips = [dict(m_Name='Animator Clip', isAttack=1, attackBaseInfo={}),
                 dict(m_Name='Summon Clip', clipSettings=settings, hitSettings={})]
        sequence = {'m_Name': name, 'tracks': [{'clips': [
            {'behaviourPrefab': {'m_PathID': i}} for i in range(len(clips))]}]}
        return recover_sequence('pl009', sequence, lambda ref: clips[ref['m_PathID']])

    def test_healing_summon_is_accessible_at_asset_index_one(self):
        for name in ('Attack2', 'Attack8'):
            with self.subTest(name=name):
                attack = self.recovered(name)[0]['AttackSetting'][0]
                self.assertEqual(attack['totalClipCount'], 2)
                self.assertEqual(attack['clipDatas'][0], {})
                summon = attack['clipDatas'][1]['clip_Summon']
                self.assertEqual(summon['ClipIndex'], 1)
                self.assertEqual(summon['BulletKind'], 2)
                self.assertEqual(summon['LifeTime'], 18)
                self.assertEqual(summon['FinishEffectSettings'], {'PrefabPath': ''})

    def test_replacement_preserves_other_attacks_and_input(self):
        stale = {'id': 'pl009', 'sequenceName': 'Attack2', 'unknown': 9,
                 'totalClipCount': 1, 'clipDatas': [{'clip_Summon': {'ClipIndex': 0}}]}
        other = {'id': 'pl010', 'sequenceName': 'Attack2', 'unknown': 10}
        existing = [{'AttackSetting': [stale, other]}]
        original = deepcopy(existing)
        result = replace_recovered_attacks(existing, self.recovered('Attack2'))
        self.assertEqual(existing, original)
        entries = result[0]['AttackSetting']
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]['unknown'], 9)
        self.assertEqual(entries[0]['totalClipCount'], 2)
        self.assertEqual(entries[1], other)

    def test_missing_debug_attack_is_added(self):
        result = replace_recovered_attacks([], self.recovered('Attack8'))
        self.assertEqual(result[0]['AttackSetting'][0]['sequenceName'], 'Attack8')

    def test_setup_selection_is_limited_to_both_healing_variants(self):
        names = sorted(HEALING_CIRCLE_SEQUENCES) + [
            'characters/player/pl009/sequences/attack3',
            'characters/player/pl010/sequences/attack2']
        manifest = {'m_Entries': [{'Name': name} for name in names]}
        self.assertEqual(healing_circle_bundle_names(manifest), manifest['m_Entries'][:2])

    def test_recovery_requires_manifest_and_bundles(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(FileNotFoundError, 'manifest'):
                recover_healing_circles(root / 'download')
            (root / 'extract').mkdir()
            manifest = root / 'extract/manifest.json'
            manifest.write_text(json.dumps({'m_Entries': []}), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'missing required'):
                recover_healing_circles(root / 'download')
            manifest.write_text(json.dumps({'m_Entries': [
                {'Name': name, 'Version': 'test'} for name in HEALING_CIRCLE_SEQUENCES
            ]}), encoding='utf-8')
            with self.assertRaisesRegex(FileNotFoundError, 'rerun setup'):
                recover_healing_circles(root / 'download')

    def test_regeneration_replaces_stale_indices_and_normalizes_masks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'debug.json'
            stale = [{'id': 'pl009', 'sequenceName': name, 'totalClipCount': 1,
                      'clipDatas': [{'clip_Summon': {'ClipIndex': 0}}]}
                     for name in ('Attack2', 'Attack8')]
            unrelated = {'id': 'pl009', 'sequenceName': 'Attack3', 'unknown': 8}
            source.write_text(json.dumps({'attackList': [{'AttackSetting': stale + [unrelated]}],
                                         'moveList': [], 'updateParameterList': []}), encoding='utf-8')
            recovered = self.recovered('Attack2') + self.recovered('Attack8')
            with patch('scripts.adapt.master_data.sequence.recover_healing_circles', return_value=recovered), \
                    patch('scripts.adapt.master_data.sequence.recover_special_skills', return_value=[]), \
                    patch('scripts.adapt.master_data.sequence.recover_minion_commands', return_value=[]):
                adapt_debug_sequences_master_data(source, root, root / 'download')
            rows = json.loads((root / 'CharacterSequenceMasterData.json').read_text())
            self.assertEqual(len(rows), 1)
            entries = json.loads(rows[0]['Data'])['AttackSetting']
            self.assertEqual(len(entries), 3)
            self.assertEqual(entries[-1], unrelated)
            for entry in entries[:2]:
                self.assertEqual(entry['totalClipCount'], 2)
                self.assertEqual(entry['clipDatas'][0], {})
                mask = entry['clipDatas'][1]['clip_Summon']['BulletAttackSettings']['IgnoreHitLayer']
                self.assertEqual(mask, {'m_Mask': -2147475456})

    def test_installed_healing_circles_use_native_lookup_indices(self):
        root = Path(__file__).resolve().parents[1] / 'src/data'
        manifest = root / 'extract/manifest.json'
        if not manifest.is_file():
            self.skipTest('Local game assets are not installed')
        entries = healing_circle_bundle_names(json.loads(manifest.read_text(encoding='utf-8-sig')))
        if not all((root / 'download' / (e['Name'] + '_' + e['Version'] + '.ab')).is_file()
                   for e in entries):
            self.skipTest('Healing circle bundles are not installed')
        attacks = [entry for row in recover_healing_circles(root / 'download')
                   for entry in row.get('AttackSetting', [])]
        self.assertEqual({entry['sequenceName'] for entry in attacks}, {'Attack2', 'Attack8'})
        for attack in attacks:
            self.assertEqual(attack['totalClipCount'], 2)
            self.assertEqual(attack['clipDatas'][0], {})
            self.assertEqual(attack['clipDatas'][1]['clip_Summon']['BulletKind'], 2)
            self.assertEqual(attack['clipDatas'][1]['clip_Summon']['ClipIndex'], 1)


if __name__ == '__main__':
    unittest.main()
