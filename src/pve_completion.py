"""Bounded HTTP completion contracts; playlog/hash remain untrusted input."""

import hashlib
import hmac
import json
import math
import re


def native_playlog_hash(raw_json, token):
    if type(raw_json) is not str or type(token) is not str:
        raise ValueError('Invalid playlog hash input.')
    if not raw_json or not token:
        return ''
    return hmac.new(token.encode('utf-8'),raw_json.encode('utf-8'),hashlib.sha256).hexdigest()


def decode_pve_playlog(payload, token):
    """Verify exact serialized bytes, then parse without trusting combat claims."""
    if type(payload) is not str or not payload or len(payload.encode('utf-8')) > 2*1024*1024:
        raise ValueError('Invalid playlog size.')
    if type(token) is not str or not token:
        raise ValueError('Prepared playlog token required.')
    signature,separator,raw_json = payload.partition(',')
    if (not separator or not re.fullmatch('[0-9a-f]{64}',signature)
            or not hmac.compare_digest(signature,native_playlog_hash(raw_json,token))):
        raise ValueError('Playlog signature does not match the prepared token.')
    def object_pairs(pairs):
        result = {}
        for key,value in pairs:
            if key in result: raise ValueError('Duplicate playlog field.')
            result[key] = value
        return result
    def constant(value):
        raise ValueError('Nonfinite playlog number.')
    try:
        value = json.loads(raw_json,object_pairs_hook=object_pairs,parse_constant=constant)
    except (json.JSONDecodeError,RecursionError) as error:
        raise ValueError('Invalid playlog JSON.') from error
    if type(value) is not dict:
        raise ValueError('Playlog must be an object.')
    pending = [(value,0)]
    count = 0
    while pending:
        entry,depth = pending.pop()
        count += 1
        if depth > 64 or count > 100000:
            raise ValueError('Playlog structure exceeds limits.')
        if type(entry) is float and not math.isfinite(entry):
            raise ValueError('Nonfinite playlog number.')
        if type(entry) is int and not -(2**63) <= entry < 2**63:
            raise ValueError('Playlog integer exceeds native range.')
        if type(entry) in (list,dict):
            pending.extend((child,depth+1) for child in (entry.values() if type(entry) is dict else entry))
    return value


def native_result_hash(battle_id, win):
    """Client consistency checksum, not authentication or victory evidence."""
    if type(battle_id) is not str or not battle_id.isascii() or type(win) is not bool:
        raise ValueError('Invalid battle hash input.')
    if not battle_id:
        return ''
    return hashlib.sha256(f'{battle_id}:{int(win)}'.encode('ascii')).hexdigest()

def completion_request(account, data, retire=False):
    fields = {'EpisodeToken','Playlog'} | (set() if retire else {'ResultHash'})
    if (type(account) is not str or not account or type(data) is not dict
            or set(data) != fields or any(type(value) is not str for value in data.values())
            or not data['EpisodeToken'] or len(data['EpisodeToken']) > 512
            or len(data['Playlog'].encode('utf-8')) > 2*1024*1024
            or not retire and len(data['ResultHash']) > 256):
        raise ValueError('Invalid raid completion request.')
    return dict(data)


def completion_response(response, retire):
    fields = {'Result'} if retire else {'Result','RankingScore','Rewards','RewardResult','SpecialDrops'}
    if type(response) is not dict or set(response) != fields or type(response['Result']) is not dict:
        raise ValueError('Complete server-owned raid result required.')
    if not retire and (type(response['Rewards']) is not list or type(response['SpecialDrops']) is not list
            or type(response['RewardResult']) is not dict
            or response['RankingScore'] is not None and type(response['RankingScore']) is not dict):
        raise ValueError('Invalid server-owned raid reward result.')
    return response
