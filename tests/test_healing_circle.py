import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from scripts.adapt.master_data.sequence import adapt_debug_sequences_master_data, adapt_debug_sequence_list
from scripts.adapt.sequence_data.tracks.Attack import adapt_attack_track
from scripts.adapt.extract_sequence_data import installed_bundle_paths
from sequence_fixtures import adapt_bundle


class HealingCircleTests(unittest.TestCase):
    def recovered(self, name):
        return adapt_attack_track({'clips': [{'behaviour': {
            'm_Name': 'Summon Clip', 'clipSettings': {
                'ClipIndex': 1, 'BulletKind': 2, 'LifeTime': 18,
                'BulletAttackSettings': {'IgnoreHitLayer': {'m_Bits': 0x80002000}},
                'FinishEffectSettings': {'PrefabPath': ''}}, 'hitSettings': {}}}]}, name, 'pl009')

    def test_healing_summon_is_accessible_at_asset_index_one(self):
        for name in ('Attack2', 'Attack8'):
            with self.subTest(name=name):
                attack = self.recovered(name)
                self.assertEqual(attack['totalClipCount'], 2)
                self.assertEqual(attack['clipDatas'][0], {})
                summon = attack['clipDatas'][1]['clip_Summon']
                self.assertEqual(summon['ClipIndex'], 1)
                self.assertEqual(summon['BulletKind'], 2)
                self.assertEqual(summon['LifeTime'], 18)
                self.assertEqual(summon['FinishEffectSettings'], {'PrefabPath': ''})

    def test_regeneration_replaces_stale_indices_and_preserves_unrelated_records(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'download/characters').mkdir(parents=True)
            source = root/'debug.json'
            stale = [{'id': 'pl009', 'sequenceName': name, 'unknown': 9, 'totalClipCount': 1,
                      'clipDatas': [{'clip_Summon': {'ClipIndex': 0}}]} for name in ('Attack2', 'Attack8')]
            unrelated = {'id': 'pl009', 'sequenceName': 'Attack3', 'unknown': 8}
            source.write_text(json.dumps({'attackList': [{'AttackSetting': stale + [unrelated]}],
                                         'moveList': [], 'updateParameterList': []}), encoding='utf-8')
            recovered = adapt_debug_sequence_list([{'AttackSetting': [self.recovered(name)]}
                                                   for name in ('Attack2', 'Attack8')])
            with patch('scripts.adapt.extract_sequence_data.extract_all_SequenceSetting_files'), \
                    patch('scripts.adapt.adapt_sequence_data.adapt_all_sequence_data', return_value=(recovered, [])):
                adapt_debug_sequences_master_data(source, root, root/'download')
            rows = json.loads((root/'CharacterSequenceMasterData.json').read_text())
            self.assertEqual(len(rows), 1)
            entries = json.loads(rows[0]['Data'])['AttackSetting']
            self.assertEqual(len(entries), 3)
            self.assertEqual(entries[-1], unrelated)
            for entry in entries[:2]:
                self.assertEqual(entry['unknown'], 9)
                self.assertEqual(entry['totalClipCount'], 2)
                self.assertEqual(entry['clipDatas'][0], {})
                mask = entry['clipDatas'][1]['clip_Summon']['BulletAttackSettings']['IgnoreHitLayer']
                self.assertEqual(mask, {'m_Mask': -2147475456})

    def test_installed_healing_circles_use_native_lookup_indices(self):
        root = Path(__file__).resolve().parents[1]/'src/data'
        if not (root/'extract/manifest.json').is_file():
            self.skipTest('Local game assets are not installed')
        try:
            paths = [path for path in installed_bundle_paths(root/'download/characters', 'player/pl009/sequences/*.ab')
                     if path.name.split('_')[0] in ('attack2', 'attack8')]
        except FileNotFoundError:
            self.skipTest('Healing circle bundles are not installed')
        self.assertEqual(len(paths), 2)
        for path in paths:
            attack = next(row['AttackSetting'][0] for row in adapt_bundle(path, 'pl009') if 'AttackSetting' in row)
            self.assertEqual(attack['totalClipCount'], 2)
            self.assertIn('clip_RegisterBuff', attack['clipDatas'][0])
            self.assertEqual(attack['clipDatas'][1]['clip_Summon']['BulletKind'], 2)
            self.assertEqual(attack['clipDatas'][1]['clip_Summon']['ClipIndex'], 1)


if __name__ == '__main__':
    unittest.main()
