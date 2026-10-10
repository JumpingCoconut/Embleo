import sys
from pathlib import Path
import unittest
from datetime import datetime,timezone,timedelta
import msgpack

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from pve_publication import EventPublication,scheduled_event_metadata
from pve_events import EpisodeCatalog,ScheduledCatalog


class PublicationTests(unittest.TestCase):
    def test_wire_event_dates_follow_authoritative_schedule_in_utc(self):
        start = datetime(2026,1,1,12,tzinfo=timezone(timedelta(hours=2)))
        end = start+timedelta(hours=1)
        catalog = ScheduledCatalog(EpisodeCatalog([],set()),[
            dict(EventId='raid',PublishStartAt=start-timedelta(minutes=5),StartAt=start,EndAt=end)],
            lambda:start)
        metadata = {'EventId':'raid','StartAt':'stale','unknown':{'keep':True}}
        event = scheduled_event_metadata(metadata,catalog,
            ranking_start=start,ranking_end=end,ranking_confirm=end+timedelta(hours=1))
        self.assertEqual(event['StartAt'],'2026-01-01T10:00:00Z')
        self.assertEqual(event['EndAt'],'2026-01-01T11:00:00Z')
        self.assertEqual(datetime.fromisoformat(event['PublishStartAt']),catalog.events['raid'][0])
        self.assertEqual(datetime.fromisoformat(event['EndAt']),catalog.events['raid'][2])
        self.assertEqual(msgpack.unpackb(msgpack.packb(event),raw=False),event)
        self.assertEqual(metadata['StartAt'],'stale')
        event['unknown']['keep'] = False
        self.assertTrue(metadata['unknown']['keep'])
        for begin,finish,confirm in ((start.replace(tzinfo=None),end,end),(end,start,end)):
            with self.assertRaises(ValueError): scheduled_event_metadata(metadata,catalog,
                ranking_start=begin,ranking_end=finish,ranking_confirm=confirm)

    def test_visibility_account_scope_and_tile_deduplication(self):
        class Catalog:
            ids = ('raid',)
            def published_event_ids(self): return self.ids
        catalog = Catalog()
        publication = EventPublication(catalog,[{'EventId':'raid'}],
            lambda account,event:{'EventId':event,'EpisodeUsers':[{'owner':account}]})
        top = {'events':[], 'pveEvents':[], 'orderdIds':[{'MasterDataId':'story','Type':1}]}
        alice = publication.apply_top('alice',top)
        bob = publication.apply_top('bob',top)
        self.assertEqual(alice['pveEvents'][0]['EpisodeUsers'][0]['owner'],'alice')
        self.assertEqual(bob['pveEvents'][0]['EpisodeUsers'][0]['owner'],'bob')
        self.assertEqual(publication.apply_top('alice',alice)['orderdIds'],alice['orderdIds'])
        self.assertEqual(top['events'],[])
        self.assertIn({'MasterDataId':'raid','Type':3},alice['orderdIds'])
        catalog.ids = ()
        self.assertEqual(publication.event_list(),[])
        hidden = publication.apply_top('alice',alice)
        self.assertEqual(hidden['events'],[])
        self.assertEqual(hidden['pveEvents'],[])
        self.assertEqual(hidden['orderdIds'],top['orderdIds'])
        with self.assertRaises(ValueError): publication.selected('alice','raid')


if __name__ == '__main__': unittest.main()
