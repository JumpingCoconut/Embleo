import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from profiles import add_all_emblems, all_emblems


class EmblemTests(unittest.TestCase):
    def test_manifest_emblems_are_unique_and_stamps_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / 'manifest.json'
            prefix = 'uiexternal/ui/common/textures/icon/emblem/icon_'
            manifest.write_text(json.dumps({'m_Entries': [
                {'Name': prefix + 'emblem_sh001_001'},
                {'Name': prefix + 'emblem_em001_002'},
                {'Name': prefix + 'emblem_sh001_001'},
                {'Name': prefix + 'unrelated'}, {'Name': None},
                {'Name': 'uiexternal/ui/common/textures/icon/stamp/icon_stamp_001'}]}), encoding='utf-8')
            top = {'stampBadgeMaster': [{'Id': 'stamp_001'}, {'Id': 'emblem_sh001_001'}],
                   'stampBadge': [{'Id': 'stamp_001'}, {'Id': 'emblem_sh001_001', 'Category': 0}],
                   'stampDeck': [{'Category': 'default', 'Deck': ['stamp_001']}]}
            add_all_emblems(top, manifest)
            self.assertEqual(all_emblems(manifest), ('emblem_em001_002', 'emblem_sh001_001'))
            self.assertEqual(top['stampBadge'][0], {'Id': 'stamp_001'})
            self.assertEqual([x['Category'] for x in top['stampBadge'][1:]], [2, 2])
            self.assertTrue(all(x['IsUse'] for x in top['stampBadge'][1:]))
            self.assertEqual(top['stampDeck'][0]['Deck'], ['stamp_001'])
            self.assertEqual(top['stampBadge'][1]['SourceId'], prefix + 'emblem_em001_002')

    def test_missing_manifest_retains_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            top = {'stampBadge': [{'Id': 'fixture'}]}
            add_all_emblems(top, Path(directory) / 'missing.json')
            self.assertEqual(top, {'stampBadge': [{'Id': 'fixture'}]})
