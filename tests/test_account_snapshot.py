import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from accounts import AccountError, SCHEMA_VERSION, read_save_snapshot
from pve_stats import CharacterCombatStats, PreparedCombatStats, SnapshotCombatStats


class AccountSnapshotTests(unittest.TestCase):
    def test_battle_visuals_follow_native_two_slot_fallback(self):
        master = dict(CharacterId='hero', Faction=1, Hp=100, Attack=20, Defense=10,
                      HpCurve='curve', AttackCurve='curve', DefenseCurve='curve',
                      HpScale=1, AttackScale=1, DefenseScale=1)
        calculator = CharacterCombatStats([master], [dict(CurveId='curve', Levels=[0])],
                                         [], [], [])
        fallback = ['default-costume', 'default-weapon']
        presentation = dict(MasterDataId='hero', CharacterName='Hero',
                            VisualEquipments=fallback)
        for visual in (None, [], ['costume'], ['costume', 'weapon']):
            with self.subTest(visual=visual):
                snapshot = {'UserCharacter.json': [dict(CharacterId='hero', Level=1,
                            Exp=0, VisualEquipment=visual)], 'UserEquipment.json': []}
                prepared = PreparedCombatStats(calculator, 'alice', snapshot,
                                               [dict(Type=1, MasterDataId='hero')])
                result = prepared.battle_character('alice', 'hero', presentation)
                expected = visual if visual is not None and len(visual) >= 2 else fallback
                self.assertEqual(result['CharacterData'][8], expected)
                result['CharacterData'][8][0] = 'changed'
                self.assertEqual(prepared.save('alice', 'UserCharacter.json'),
                                 snapshot['UserCharacter.json'])
                self.assertEqual(presentation['VisualEquipments'], fallback)

    def test_prepared_stats_remain_frozen_after_save_edit(self):
        master = dict(CharacterId='hero', Faction=1, Hp=100, Attack=20, Defense=10,
                      HpCurve='curve', AttackCurve='curve', DefenseCurve='curve',
                      HpScale=1, AttackScale=1, DefenseScale=1)
        calculator = CharacterCombatStats([master], [dict(CurveId='curve', Levels=[0, 1])],
                                         [], [], [])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'accounts.sqlite3'
            db = sqlite3.connect(path)
            try:
                db.execute('PRAGMA user_version=' + str(SCHEMA_VERSION))
                db.execute('CREATE TABLE accounts(id TEXT PRIMARY KEY)')
                db.execute('CREATE TABLE saves(account_id TEXT,name TEXT,value TEXT)')
                db.execute("INSERT INTO accounts VALUES('alice')")
                for name, value in (
                        ('UserCharacter.json', [dict(CharacterId='hero', Level=1, Exp=42)]),
                        ('UserEquipment.json', []),
                        ('ordering.json', [dict(Type=1, MasterDataId='hero')])):
                    db.execute('INSERT INTO saves VALUES(?,?,?)', ('alice', name, json.dumps(value)))
                db.commit()
                provider = SnapshotCombatStats(calculator, path,
                    lambda snapshot: snapshot['ordering.json'], ['ordering.json'])
                prepared = provider.prepare('alice')
                db.execute("UPDATE saves SET value=? WHERE name='UserCharacter.json'",
                           (json.dumps([dict(CharacterId='hero', Level=2, Exp=90)]),))
                db.commit()
                self.assertEqual(prepared.character('alice', 'hero'),
                                 dict(Hp=100, Attack=20, Defense=10, Power=130))
                self.assertEqual(provider.prepare('alice').character('alice', 'hero')['Power'], 260)
                self.assertEqual(prepared.character('alice', 'hero', {'hero': 2})['Power'], 260)
                self.assertEqual(prepared.character('alice', 'hero')['Power'], 130)
                self.assertEqual(prepared.initial_resources('alice', 'hero'), {'Hp': 100, 'Mp': 0})
                self.assertEqual(prepared.initial_resources('alice', 'hero', {'hero': 2}),
                                 {'Hp': 200, 'Mp': 0})
                presentation = dict(MasterDataId='hero', CharacterName='Hero',
                                    VisualEquipments=['default-costume', 'default-weapon'])
                assembled = prepared.battle_character('alice', 'hero', presentation, {'hero': 2})
                self.assertEqual(assembled['PlayCharacter'],
                                 dict(characterId='hero', level=2, exp=42, hp=200, sp=0))
                self.assertEqual(assembled['CharacterData'],
                                 {1:'hero', 2:'hero', 3:'Hero', 4:2, 5:42, 6:200, 7:0,
                                  8:['default-costume', 'default-weapon'], 9:[], 10:[]})
                assembled['CharacterData'][8].append('changed')
                self.assertEqual(presentation['VisualEquipments'], ['default-costume', 'default-weapon'])
                self.assertEqual(prepared.battle_character('alice', 'hero', presentation)
                                 ['CharacterData'][8], ['default-costume', 'default-weapon'])
                row = prepared.save('alice', 'UserCharacter.json')[0]
                self.assertEqual(row['Exp'], 42)
                row['Exp'] = -1
                self.assertEqual(prepared.save('alice', 'UserCharacter.json')[0]['Exp'], 42)
                with self.assertRaises(ValueError):
                    prepared.character('bob', 'hero')
                with self.assertRaises(ValueError):
                    prepared.save('bob', 'UserCharacter.json')
                self.assertEqual(json.loads(db.execute(
                    "SELECT value FROM saves WHERE name='UserCharacter.json'").fetchone()[0])[0]['Exp'], 90)
            finally:
                db.close()

    def test_snapshot_is_detached_scoped_and_available_during_wal_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'accounts.sqlite3'
            db = sqlite3.connect(path)
            try:
                db.execute('PRAGMA journal_mode=WAL')
                db.execute('PRAGMA user_version=' + str(SCHEMA_VERSION))
                db.execute('CREATE TABLE accounts(id TEXT PRIMARY KEY)')
                db.execute('CREATE TABLE saves(account_id TEXT,name TEXT,value TEXT)')
                for account, level in (('alice', 1), ('bob', 9)):
                    db.execute('INSERT INTO accounts VALUES(?)', (account,))
                    for name in ('UserCharacter.json', 'UserEquipment.json'):
                        db.execute('INSERT INTO saves VALUES(?,?,?)',
                                   (account, name, json.dumps([{'Level': level}])))
                db.commit()
                db.execute('BEGIN IMMEDIATE')
                db.execute('UPDATE saves SET value=? WHERE account_id=?',
                           ('[{"Level":2}]', 'alice'))
                names = ['UserCharacter.json', 'UserEquipment.json']
                snapshot = read_save_snapshot(path, 'alice', names)
                self.assertEqual([snapshot[name][0]['Level'] for name in names], [1, 1])
                snapshot[names[0]][0]['Level'] = 100
                db.commit()
                self.assertEqual(read_save_snapshot(path, 'alice', names)[names[0]], [{'Level': 2}])
                self.assertEqual(read_save_snapshot(path, 'bob', names)[names[0]], [{'Level': 9}])
                for account, requested in (('absent', names), ('alice', ['absent']),
                                           ('alice', [names[0], names[0]])):
                    with self.assertRaises(AccountError):
                        read_save_snapshot(path, account, requested)
            finally:
                db.close()

    def test_missing_or_old_database_is_never_created_or_migrated(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'accounts.sqlite3'
            with self.assertRaises(sqlite3.OperationalError):
                read_save_snapshot(path, 'alice', ['UserCharacter.json'])
            self.assertFalse(path.exists())
            db = sqlite3.connect(path)
            try:
                db.execute('PRAGMA user_version=1')
            finally:
                db.close()
            before = path.read_bytes()
            with self.assertRaises(RuntimeError):
                read_save_snapshot(path, 'alice', ['UserCharacter.json'])
            self.assertEqual(path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
