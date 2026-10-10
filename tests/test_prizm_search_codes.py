import sys
import unittest
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from prizm_rooms import Rooms, RoomError
from prizm_room_service import RoomService
from prizm_sessions import SessionRegistry
from pve_events import EpisodeCatalog, ScheduledCatalog
from prizm_admission import admission_payload
from test_prizm_lobby import player


class SearchCodeTests(unittest.TestCase):
    def test_native_slots_are_one_based_and_reuse_departed_slot(self):
        service = self.service()
        room, tcp, _ = service.create(player('host'), 'episode', 'v', False, 1, 1, (60, 3, 20))
        identity = room['RoomId']
        self.assertEqual(room['Players'][0]['Order'], 1)
        self.assertEqual(service.registry.open(tcp).admission.player_id, 1)
        for name, expected in [('second', 2), ('third', 3), ('fourth', 4)]:
            joined, credential, _ = service.join(identity, player(name), 'v')
            self.assertEqual(next(p['Order'] for p in joined['Players'] if p['UserId'] == name), expected)
            self.assertEqual(service.registry.open(credential).admission.player_id, expected)
        with self.assertRaises(RoomError): service.join(identity, player('fifth'), 'v')
        service.leave('second', identity)
        joined, credential, _ = service.join(identity, player('replacement'), 'v')
        self.assertEqual([p['Order'] for p in joined['Players']], [1, 2, 3, 4])
        self.assertEqual(service.registry.open(credential).admission.player_id, 2)

    def service(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        catalog = ScheduledCatalog(EpisodeCatalog([dict(
            EpisodePveEventId='link', EventId='event', EpisodeId='episode',
            RequiredPower=100, Difficulty=1, MinVerIOS='1.6.0',
            MinVerAndroid='1.6.0')], {'episode'}), [dict(
                EventId='event', PublishStartAt=now, StartAt=now,
                EndAt=now + timedelta(days=1))], lambda: now)
        return RoomService(Rooms(4), SessionRegistry(), event_catalog=catalog,
            eligibility_provider=lambda account: dict(Power=100, Platform='android',
                                                       ClientVersion='1.6.0'),
            player_provider=player,
            room_settings_provider=lambda episode: dict(Mode=1, SuspendLimits=(60, 3, 20)),
            room_view_provider=lambda account, room: room,
            connection_provider=lambda room, tcp, udp: admission_payload(
                room['RoomId'], room['SearchId'], tcp, udp,
                'localhost', 1234, 'localhost', 1235))

    def test_collisions_retry_and_leading_zeroes_survive(self):
        rooms = Rooms(4)
        with patch('prizm_rooms.secrets.randbelow', side_effect=[12, 12, 13]):
            first = rooms.create(player('a'), 'episode', 'v', False, 1, 1, (60, 3, 20))
            second = rooms.create(player('b'), 'episode', 'v', False, 1, 1, (60, 3, 20))
        self.assertEqual(first['SearchId'], '0000012')
        self.assertEqual(second['SearchId'], '0000013')
        self.assertEqual(rooms.resolve_room_id(first['SearchId']), first['RoomId'])
        self.assertEqual(rooms.resolve_room_id(first['RoomId']), first['RoomId'])
        rooms.join(first['RoomId'], player('guest'), 'v')
        rooms.leave('a', first['RoomId'])
        self.assertEqual(rooms.resolve_room_id(first['SearchId']), first['RoomId'])
        rooms.leave('guest', first['RoomId'])
        with self.assertRaises(RoomError): rooms.resolve_room_id(first['SearchId'])
        self.assertEqual(rooms.resolve_room_id(second['SearchId']), second['RoomId'])

    def test_collision_exhaustion_leaves_existing_room_untouched(self):
        rooms = Rooms(4)
        with patch('prizm_rooms.secrets.randbelow', return_value=12):
            room = rooms.create(player('a'), 'episode', 'v', False, 1, 1, (60, 3, 20))
            with self.assertRaises(RoomError):
                rooms.create(player('b'), 'episode', 'v', False, 1, 1, (60, 3, 20))
        self.assertEqual(set(rooms.memberships), {'a'})
        self.assertEqual(rooms.search_ids, {room['SearchId']: room['RoomId']})

    def test_code_lookup_preserves_event_version_and_join_access(self):
        service = self.service()
        admission = service.create_http('host', 'link', 'v', 2)['Prizm']
        code, identity = admission['SearchId'], admission['RoomId']
        self.assertRegex(code, r'^[0-9]{7}$')
        self.assertEqual(service.info_event('guest', 'event', code, 'v')['RoomId'], identity)
        for event, version in [('other', 'v'), ('event', 'wrong')]:
            with self.assertRaises(RoomError):
                service.info_event('guest', event, code, version)
        with self.assertRaises(RoomError): service.join_http('guest', code, 'v', 1)
        with self.assertRaises(RoomError): service.join_http('guest', code, 'wrong', 3)
        self.assertNotIn('guest', service.rooms.memberships)
        result = service.join_http('guest', code, 'v', 3)['Prizm']
        self.assertEqual((result['RoomId'], result['SearchId']), (identity, code))
        self.assertEqual(service.registry.open(result['JwtTcp']).admission.room_id, identity)

    def test_provider_cannot_substitute_another_live_room_code(self):
        service = self.service()
        first = service.create_http('host', 'link', 'v', 1)['Prizm']
        service.connection_provider = lambda room, tcp, udp: admission_payload(
            room['RoomId'], first['SearchId'], tcp, udp,
            'localhost', 1234, 'localhost', 1235)
        with self.assertRaises(RoomError): service.create_http('other', 'link', 'v', 1)
        self.assertNotIn('other', service.rooms.memberships)
        self.assertEqual(service.rooms.search_ids, {first['SearchId']: first['RoomId']})
        self.assertFalse(any(record[0].account_id == 'other'
                             for record in service.registry.credentials.values()))


if __name__ == '__main__':
    unittest.main()
