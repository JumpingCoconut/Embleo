import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from pve_resources import EventResources
from pve_publication import EventPublication


class ResourcesTests(unittest.TestCase):
    def test_publication_preflights_native_images_and_optional_decoration(self):
        event = dict(EventId='raid',LogoId='boss',DecoId='calendar')
        names = ['uiexternal/ui/common/textures/icon/pve/raid',
                 'lang_en/textures/icon/pve/pve_en_boss',
                 'lang_ja/textures/icon/pve/pve_ja_boss']
        names += ['uiexternal/ui/common/textures/icon/pve/calendar/calendar_'+suffix
                  for suffix in ('01','02','03','05')]
        names += [f'lang_{language}/textures/icon/pve/pve_{language}_calendar_04'
                  for language in ('en','ja')]
        resources = EventResources(names,['en','ja'])
        self.assertEqual(len(resources(event)),9)
        self.assertEqual(len(resources(dict(EventId='raid',LogoId='',DecoId=''))),1)
        class Catalog:
            def published_event_ids(self): return ('raid',)
        callback = lambda account,event:dict(EventId=event)
        publication = EventPublication(Catalog(),[event],callback,resource_validator=resources)
        self.assertEqual(publication.event_list(),[event])
        for bad in (event | {'EventId':'unknown'},event | {'LogoId':'missing'},
                    event | {'DecoId':'missing'},event | {'EventId':'../raid'}):
            with self.assertRaises(ValueError):
                EventPublication(Catalog(),[bad],callback,resource_validator=resources)
        with self.assertRaises(ValueError): EventResources(names[:-1],['en','ja'])(event)
