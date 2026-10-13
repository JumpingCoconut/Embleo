"""Native account total power, calculated from account saves and installed masters."""

import json
from functools import lru_cache
from pathlib import Path

from accounts import AccountError
from pve_stats import CharacterCombatStats

MASTER_FILES = ('CharacterMasterData.json', 'TemporaryLevelStatusCurveCharacterMasterData.json',
                'EquipmentMasterData.json', 'TemporaryLevelStatusCurveEquipmentMasterData.json',
                'BuffMasterData.json')


@lru_cache(maxsize=4)
def _calculator(paths):
    rows = []
    for name, modified, size in paths:
        with Path(name).open(encoding='utf-8-sig') as stream:
            rows.append(json.load(stream))
    return CharacterCombatStats(*rows)


def installed_calculator(root):
    paths = [Path(root) / 'masterdata' / name for name in MASTER_FILES]
    return _calculator(tuple((str(path.resolve()),path.stat().st_mtime_ns,path.stat().st_size)
                             for path in paths))


def total_power(calculator, store, account, content_order=None):
    characters = store.read(account,'UserCharacter.json')
    equipment = store.read(account,'UserEquipment.json')
    # HomeSceneUtility.CharacterTotalPower (0x32EB530) adds the powers of
    # character entries in the content list. Related-character order is kept.
    try:
        if (type(characters) is not list or type(equipment) is not list
                or any(type(row) is not dict for row in characters + equipment)):
            raise ValueError('Invalid account combat records.')
        owned = {row['CharacterId'] for row in characters}
        ordering = ([dict(Type=1,MasterDataId=row['CharacterId']) for row in characters]
                    if content_order is None else
                    [row for row in content_order if row['Type'] == 1 and row['MasterDataId'] in owned])
        value = sum(calculator.power(row['MasterDataId'],characters,equipment,ordering)
                    for row in ordering)
        if type(value) is not int or not 0 <= value < 2**31:
            raise ValueError('Account power exceeds native range.')
        return value
    except (ValueError,KeyError,TypeError,AttributeError) as error:
        raise AccountError('Account combat power is unavailable.') from error
