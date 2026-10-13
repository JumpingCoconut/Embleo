"""Opt-in combat playtest helpers; never change account saves or disk masters."""

import json
import os
import sys


INSTANT_MYSTIC_ENV = 'EMBLEO_INSTANT_MYSTIC_ARTES'
GAUGE_BUFF_ID = 'embleo_debug_mystic_gauge'


def apply_instant_mystic_artes(master_group, *, enabled=None):
    """Refill the player's skill gauge on the first tick and after each use.

    Native DoT SkillGauge subtracts EffectValue from the current gauge, so a
    negative fixed value heals it. StartUpBuffIdList installs it on spawn.
    """
    # Raid assembly shares the server's source switch without importing the
    # Flask application (or creating a second app when run as __main__).
    if enabled is None:
        enabled = any(getattr(sys.modules.get(name), 'INSTANT_MYSTIC_ARTES', False)
                      for name in ('server', '__main__'))
    if not enabled and os.environ.get(INSTANT_MYSTIC_ENV) != '1':
        return master_group
    for character in master_group['characters']:
        parameters = json.loads(character['UniqueParamData'] or '{}')
        entries = parameters.setdefault('m_Param_StringArray', [])
        startup = next((entry for entry in entries if entry['Key'] == 'StartUpBuffIdList'), None)
        if startup is None:
            startup = {'Key': 'StartUpBuffIdList', 'Value': []}
            entries.append(startup)
        if GAUGE_BUFF_ID not in startup['Value']:
            startup['Value'].append(GAUGE_BUFF_ID)
        character['UniqueParamData'] = json.dumps(parameters)
    if not any(buff['ID'] == GAUGE_BUFF_ID for buff in master_group['buff']):
        master_group['buff'].append({
            'ID': GAUGE_BUFF_ID, 'EffectType': '', 'CreateType': 'DoT',
            'EffectTime': [-1.0], 'EffectValue': [-300.0], 'VFXID': '',
            'OverwriteGroup': '', 'Priority': 0,
            'ExParam': json.dumps({
                'm_Param_String': [{'Key': 'EffectType', 'Value': 'SkillGauge'}],
                'm_Param_Float': [{'Key': 'IntervalTime', 'Value': 0.033},
                                  {'Key': 'OffsetStartTime', 'Value': 0.0}],
                'm_Param_Int': [{'Key': 'FixedDamage', 'Value': 1}],
                'm_Param_StringArray': [], 'm_Param_FloatArray': [], 'm_Param_IntArray': [],
            }),
        })
    return master_group
