import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from scripts.adapt.master_data.sequence import merge_sequence_masters
from scripts.adapt.sequence_data.tracks.Move import adapt_move_track


class EnemySequenceTests(unittest.TestCase):
    def test_enemy_clips_without_serialized_indices_use_timeline_order(self):
        clips = [{'behaviour': dict(m_Name='EnemyMove Clip', direction=dict(x=0,y=0,z=1), speed=s)}
                 for s in (0.8, 1.2)]
        row = adapt_move_track({'clips': clips}, 'Walk010', 'em0001_001')
        self.assertEqual(row['totalMoveCount'], 2)
        self.assertEqual(row['moveCount'], [0, 1])
        self.assertEqual(row['speed'], [0.8, 1.2])

    def test_native_lookup_can_index_every_generated_movement_clip(self):
        clips = [{'behaviour': dict(m_Name='EnemyMove Clip', clipIndex=i,
                  direction=dict(x=0, y=0, z=1), speed=1.5)} for i in (0, 2)]
        row = adapt_move_track({'clips': clips}, 'Action040', 'em0017_001')
        # DataSet.Get_MoveData checks direction/speed lengths and totalMoveCount,
        # then indexes moveCount[index] and requires it to equal index.
        for index in range(row['totalMoveCount']):
            self.assertEqual(row['moveCount'][index], index)
            self.assertIn('z', row['direction'][index])
            self.assertIsInstance(row['speed'][index], (int, float))
        self.assertEqual(row['speed'][1], 0)

    def test_merging_movement_preserves_attacks_and_other_sequences(self):
        attack = dict(EnemyId='em0001_001', Category='AttackSetting', Data='native attack payload')
        def moves(values):
            return dict(EnemyId='em0001_001', Category='MoveSetting', Data=json.dumps({'MoveSetting':values}))
        old = moves([dict(sequenceName='Walk010', speed=[0]), dict(sequenceName='Other', speed=[2])])
        new = moves([dict(sequenceName='Walk010', speed=[0.8])])
        result = merge_sequence_masters([attack, old], [new], 'EnemyId')
        self.assertIs(result[0], attack)
        rows = json.loads(result[1]['Data'])['MoveSetting']
        self.assertEqual({r['sequenceName']:r['speed'] for r in rows}, {'Walk010':[0.8], 'Other':[2]})
        self.assertEqual(json.loads(old['Data'])['MoveSetting'][0]['speed'], [0])

    def test_full_attack_extraction_preserves_other_debug_sequences(self):
        def attacks(values):
            return dict(EnemyId='enemy', Category='AttackSetting', Data=json.dumps({'AttackSetting': values}))
        old = attacks([dict(sequenceName='Attack1', unknown=3, clipDatas=[{'old': True}]),
                       dict(sequenceName='DebugOnly', clipDatas=[{'keep': True}])])
        new = attacks([dict(sequenceName='Attack1', clipDatas=[{'enemy_Hit': {'DamageRate': 2}}])])
        result = merge_sequence_masters([old], [new], 'EnemyId')
        entries = json.loads(result[0]['Data'])['AttackSetting']
        self.assertEqual(entries[0]['clipDatas'], [{'enemy_Hit': {'DamageRate': 2}}])
        self.assertEqual(entries[0]['unknown'], 3)
        self.assertEqual(entries[1]['sequenceName'], 'DebugOnly')


if __name__ == '__main__':
    unittest.main()
