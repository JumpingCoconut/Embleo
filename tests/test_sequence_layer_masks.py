import sys
import unittest
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from scripts.adapt.sequence_data.tracks.Attack import normalize_IgnoreHitLayer


class SequenceLayerMaskTests(unittest.TestCase):
    def adapt(self, settings):
        original = deepcopy(settings)
        result = normalize_IgnoreHitLayer(settings)
        self.assertEqual(settings, original)
        return result

    def test_nested_summon_mask_uses_runtime_field(self):
        settings = {'clip_Summon': {'BulletAttackSettings': {
            'IgnoreHitLayer': {'m_Bits': 134225920}, 'AttackDamageRate': 7}}}
        result = self.adapt(settings)['clip_Summon']['BulletAttackSettings']
        self.assertEqual(result['IgnoreHitLayer'], {'m_Mask': 134225920})
        self.assertEqual(result['AttackDamageRate'], 7)
        self.assertTrue(result['IgnoreHitLayer']['m_Mask'] & (1 << 13))

    def test_masks_are_normalized_across_clip_families(self):
        for family in ('clip_Gun', 'clip_LookGun', 'clip_Summon', 'clip_Grenade'):
            with self.subTest(family=family):
                result = self.adapt({family: {'IgnoreHitLayer': {'m_Bits': 0}}})
                self.assertEqual(result[family]['IgnoreHitLayer'], {'m_Mask': 0})

    def test_runtime_mask_and_unrelated_fields_are_preserved(self):
        settings = {'clip_Gun': {'IgnoreHitLayer': {'m_Mask': -1, 'future': 2},
                                 'unknown': {'m_Bits': 12}, 'other': [1, None]}}
        self.assertEqual(self.adapt(settings), settings)

    def test_normalization_preserves_unknown_mask_fields(self):
        result = self.adapt({'IgnoreHitLayer': {'m_Bits': 8192, 'future': 3}})
        self.assertEqual(result['IgnoreHitLayer'], {'m_Mask': 8192, 'future': 3})

    def test_unsigned_asset_mask_has_signed_runtime_representation(self):
        result = self.adapt({'IgnoreHitLayer': {'m_Bits': 0xffffffff}})
        self.assertEqual(result['IgnoreHitLayer'], {'m_Mask': -1})

    def test_existing_runtime_field_wins_over_asset_alias(self):
        settings = {'IgnoreHitLayer': {'m_Mask': 8192, 'm_Bits': 0}}
        self.assertEqual(self.adapt(settings), settings)

    def test_enemy_masks_use_the_same_conversion(self):
        setting = self.adapt({'enemy_Hit': {'IgnoreHitLayer': {'m_Bits': 8192}}})
        self.assertEqual(setting['enemy_Hit']['IgnoreHitLayer'],
                          {'m_Mask': 8192})


if __name__ == '__main__':
    unittest.main()
