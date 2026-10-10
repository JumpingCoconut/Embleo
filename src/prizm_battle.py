"""Native-verified battle loading, object creation and status message contracts."""

import msgpack
import math
import copy
import json

from prizm_protocol import command_message, read_command_message, read_rpc_request, ProtocolError
from prizm_lobby import player_payload


BATTLE_SERVICE = 2000


def minion_recovery_parameters_match(original, current):
    """Freeze creation identity while allowing native magic-decoy HP resends.

    Unknown parameter formats retain exact equality. Spawn authorization remains
    the provider's responsibility, including the initial decoy maximum HP.
    """
    if original == current:
        return True
    def unique_fields(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate minion parameter.')
            result[key] = value
        return result
    try:
        values = [json.loads(value, object_pairs_hook=unique_fields)
                  for value in (original, current)]
    except (ValueError, TypeError, RecursionError):
        return False
    for value in values:
        if (type(value) is not dict
                or set(value) != {'MaxHP', 'HP', 'Base_LoadPath', 'AddPrefabInfos'}
                or type(value['MaxHP']) is not int or not 0 <= value['MaxHP'] <= 2147483647
                or type(value['HP']) is not int or not 0 <= value['HP'] <= value['MaxHP']
                or type(value['Base_LoadPath']) is not str
                or type(value['AddPrefabInfos']) is not list
                or any(type(item) is not str for item in value['AddPrefabInfos'])):
            return False
    return ({key: value for key, value in values[0].items() if key != 'HP'}
            == {key: value for key, value in values[1].items() if key != 'HP'})


def game_over_request(body):
    command,request_id,payload = read_rpc_request(body)
    if command not in (0,26):
        raise ProtocolError('Unsupported battle completion RPC.')
    try:
        request = msgpack.unpackb(payload,raw=False,strict_map_key=False,
                                 max_map_len=4,max_array_len=32,max_str_len=4096,max_bin_len=0)
    except (ValueError, msgpack.UnpackException):
        raise ProtocolError('Invalid battle completion payload.') from None
    if type(request) is not dict:
        raise ProtocolError('Invalid battle completion map.')
    if command == 26:
        if request:
            raise ProtocolError('Battle completion confirmation must be empty.')
        return command,request_id,None
    if (any(type(key) is not int or key not in (1,2,3,4) for key in request)
            or type(request.get(1,0)) is not int or request.get(1,0) not in range(5)
            or request.get(2) is not None and type(request[2]) is not list
            or request.get(3) is not None and type(request[3]) is not str
            or type(request.get(4,0)) is not int or not -(2**63) <= request.get(4,0) < 2**63):
        raise ProtocolError('Invalid battle completion fields.')
    damages = request.get(2) or []
    for damage in damages:
        if (type(damage) is not dict or any(type(key) is not int or key not in (1,2) for key in damage)
                or type(damage.get(1)) is not str or not damage[1]
                or type(damage.get(2,0)) is not int or not -(2**31) <= damage.get(2,0) < 2**31):
            raise ProtocolError('Invalid battle damage summary.')
    if len({damage[1] for damage in damages}) != len(damages):
        raise ProtocolError('Duplicate battle damage summary.')
    return command,request_id,{1:request.get(1,0),2:damages,3:request.get(3) or '',4:request.get(4,0)}


def game_over_reply(report):
    return msgpack.packb({1:report[2],2:report[4]},use_bin_type=True)


def game_over_notification(report):
    return command_message(1,msgpack.packb(report,use_bin_type=True))


def game_over_confirm_reply(report):
    return msgpack.packb({1:1 if report is not None else 0,2:report},use_bin_type=True)


def object_effect_request(body):
    command,payload = read_command_message(body)
    sizes = {20:7,29:11,31:3,33:6}
    if command not in sizes:
        raise ProtocolError('Unsupported object effect command.')
    try:
        request = msgpack.unpackb(payload,raw=False,strict_map_key=False,
                                 max_map_len=16,max_array_len=64,max_str_len=4096,max_bin_len=65536)
    except (ValueError, msgpack.UnpackException):
        raise ProtocolError('Invalid object effect payload.') from None
    if (type(request) is not dict or 1 not in request
            or any(type(key) is not int or key not in range(1,sizes[command]+1) for key in request)):
        raise ProtocolError('Invalid object effect fields.')
    guid = request[1]
    if (type(guid) is not dict or set(guid) != {1} or type(next(iter(guid))) is not int
            or type(guid[1]) is not bytes or len(guid[1]) != 16 or guid[1] == bytes(16)):
        raise ProtocolError('Invalid object effect GUID.')
    integer_fields = {20:(2,5),29:(3,4,6,7,8),31:(2,),33:(2,3)}[command]
    if any(type(request.get(key,0)) is not int or not -(2**31) <= request.get(key,0) < 2**31
           for key in integer_fields):
        raise ProtocolError('Invalid object effect integer.')
    if command == 20:
        if (type(request.get(3,0)) is not int or not 0 <= request.get(3,0) < 2**32
                or type(request.get(4,0.0)) not in (int,float) or not math.isfinite(request.get(4,0.0))
                or any(type(request.get(key,False)) is not bool for key in (6,7))):
            raise ProtocolError('Invalid status action values.')
    elif command == 29:
        if (type(request.get(2,0)) is not int or not -(2**63) <= request.get(2,0) < 2**63
                or request.get(5) is not None and (type(request[5]) is not list
                    or any(type(value) is not int or not -(2**31) <= value < 2**31 for value in request[5]))
                or type(request.get(9,0.0)) not in (int,float) or not math.isfinite(request.get(9,0.0))
                or request.get(10) is not None and type(request[10]) is not dict):
            raise ProtocolError('Invalid buff registration values.')
        value = request.get(10) or {}
        if (any(type(key) is not int or key != 1 for key in value)
                or type(value.get(1,0.0)) not in (int,float) or not math.isfinite(value.get(1,0.0))):
            raise ProtocolError('Invalid buff value.')
    elif command == 33:
        if (request.get(4) is not None and type(request[4]) is not bytes
                or request.get(5) is not None and type(request[5]) is not str):
            raise ProtocolError('Invalid buff command values.')
    recipient_field = {29:11,31:3,33:6}.get(command)
    if recipient_field and request.get(recipient_field) is not None and type(request[recipient_field]) is not str:
        raise ProtocolError('Invalid object effect recipient.')
    return command,request,request.get(recipient_field) or None


def object_effect_notification(command, request):
    if command not in (20,29,31,33):
        raise ProtocolError('Unsupported object effect command.')
    return command_message(command+1,msgpack.packb(request,use_bin_type=True))


def create_minion_request(body):
    command,payload = read_command_message(body)
    if command != 27:
        raise ProtocolError('Expected minion creation command.')
    try:
        request = msgpack.unpackb(payload,raw=False,strict_map_key=False,
                                 max_map_len=7,max_array_len=0,max_str_len=4096,max_bin_len=16)
    except (ValueError, msgpack.UnpackException):
        raise ProtocolError('Invalid minion creation payload.') from None
    if (type(request) is not dict or any(type(key) is not int or key not in range(1,8) for key in request)
            or any(key not in request for key in (1,2,3,4,5))):
        raise ProtocolError('Invalid minion creation fields.')
    for key in (1,2):
        guid = request[key]
        if (type(guid) is not dict or set(guid) != {1} or type(next(iter(guid))) is not int
                or type(guid[1]) is not bytes or len(guid[1]) != 16 or guid[1] == bytes(16)):
            raise ProtocolError('Invalid minion or owner GUID.')
    if request[1] == request[2]:
        raise ProtocolError('Minion cannot own itself.')
    for key,dimensions in ((3,3),(4,4)):
        vector = request[key]
        if (type(vector) is not dict
                or any(type(field) is not int or field not in range(1,dimensions+1) for field in vector)
                or any(type(value) not in (int,float) or not math.isfinite(value) for value in vector.values())):
            raise ProtocolError('Invalid minion transform.')
    if (type(request[5]) is not str or not request[5]
            or any(type(request.get(key,'')) is not str for key in (6,7))):
        raise ProtocolError('Invalid minion identity, parameters or recipient.')
    return request | {6:request.get(6,''),7:request.get(7,'')}


def create_minion_notification(request):
    return command_message(28,msgpack.packb(request,use_bin_type=True))


def object_liveness_request(body, account_id):
    command,payload = read_command_message(body)
    if command not in (22,24):
        raise ProtocolError('Unsupported object liveness command.')
    try:
        request = msgpack.unpackb(payload,raw=False,strict_map_key=False,
                                 max_map_len=4,max_array_len=0,max_str_len=128,max_bin_len=16)
    except (ValueError, msgpack.UnpackException):
        raise ProtocolError('Invalid object liveness payload.') from None
    fields = (1,2) if command == 22 else (1,2,3,4)
    if (type(request) is not dict or any(type(key) is not int or key not in fields for key in request)
            or type(request.get(1)) is not str or request[1] != account_id):
        raise ProtocolError('Invalid object liveness sender.')
    guid = request.get(2 if command == 22 else 3)
    if (type(guid) is not dict or set(guid) != {1} or type(next(iter(guid))) is not int
            or type(guid[1]) is not bytes or len(guid[1]) != 16 or guid[1] == bytes(16)):
        raise ProtocolError('Invalid object liveness GUID.')
    if command == 24 and (type(request.get(2)) is not str or not request[2]
                          or type(request.get(4,False)) is not bool):
        raise ProtocolError('Invalid object alive-confirm recipient or flag.')
    return command,request


def object_liveness_notification(command, request):
    if command not in (22,24):
        raise ProtocolError('Unsupported object liveness command.')
    return command_message(command+1,msgpack.packb(request,use_bin_type=True))


def object_action_request(body):
    command,payload = read_command_message(body)
    if command not in (4,6,8,14,16):
        raise ProtocolError('Unsupported object action command.')
    try:
        request = msgpack.unpackb(payload,raw=False,strict_map_key=False,
                                 max_map_len=16,max_array_len=32,max_str_len=512,max_bin_len=16)
    except (ValueError, msgpack.UnpackException):
        raise ProtocolError('Invalid object action payload.') from None
    fields = (range(1,3) if command == 14 else range(1,9) if command == 4 else range(1,6) if command == 16
              else range(1,5) if command == 6 else range(1,4))
    if (type(request) is not dict or 1 not in request
            or any(type(key) is not int or key not in fields for key in request)):
        raise ProtocolError('Invalid object action fields.')
    guid = request[1]
    if (type(guid) is not dict or set(guid) != {1} or type(next(iter(guid))) is not int
            or type(guid[1]) is not bytes or len(guid[1]) != 16 or guid[1] == bytes(16)):
        raise ProtocolError('Invalid object action GUID.')
    if command == 14:
        if type(request.get(2,'')) is not str:
            raise ProtocolError('Invalid object destruction recipient.')
    elif command == 16:
        if any(request.get(key) is not None and type(request[key]) is not dict for key in (2,3,4,5)):
            raise ProtocolError('Invalid reflection data.')
        damage = request.get(5) or {}
        if (any(type(key) is not int or key not in (1,2) for key in damage)
                or type(damage.get(1,'')) is not str
                or type(damage.get(2,0)) is not int or not -(2**31) <= damage.get(2,0) < 2**31):
            raise ProtocolError('Invalid damage credit or integer.')
        receiver = request.get(3) or {}
        if (any(type(key) is not int or key not in (1,2) for key in receiver)
                or type(receiver.get(2,'')) is not str):
            raise ProtocolError('Invalid reflection receiver.')
        for container in (request.get(2) or {},receiver):
            reference = container.get(1)
            if reference is not None and (type(reference) is not dict
                    or any(type(key) is not int or key != 1 for key in reference)
                    or reference.get(1) is not None and (type(reference[1]) is not bytes or len(reference[1]) != 16)):
                raise ProtocolError('Invalid reflection object reference.')
    elif command == 4:
        if (any(request.get(key) is not None and type(request[key]) is not dict for key in (2,5,6,7))
                or type(request.get(8,0)) is not int or not 0 <= request.get(8,0) < 2**32):
            raise ProtocolError('Invalid battle action data or sequence.')
        for key,dimensions in ((3,3),(4,4)):
            vector = request.get(key,{})
            if (type(vector) is not dict
                    or any(type(field) is not int or field not in range(1,dimensions+1) for field in vector)
                    or any(type(value) not in (int,float) or not math.isfinite(value) for value in vector.values())):
                raise ProtocolError('Invalid battle action transform.')
    elif command == 6:
        if type(request.get(2,0)) is not int or not -(2**31) <= request.get(2,0) < 2**31:
            raise ProtocolError('Invalid movement action type.')
        for key in (3,4):
            vector = request.get(key,{})
            if (type(vector) is not dict
                    or any(type(field) is not int or field not in (1,2,3) for field in vector)
                    or any(type(value) not in (int,float) or not math.isfinite(value) for value in vector.values())):
                raise ProtocolError('Invalid movement action vector.')
    elif (request.get(2) is not None and type(request[2]) is not dict
            or request.get(3) is not None and (type(request[3]) is not list
                or any(type(value) is not str for value in request[3]))):
        raise ProtocolError('Invalid attack target or names.')
    return command,request


def object_action_notification(command, request):
    if command not in (4,6,8,14,16):
        raise ProtocolError('Unsupported object action command.')
    return command_message(command+1,msgpack.packb(request,use_bin_type=True))


def update_status_request(body):
    command,payload = read_command_message(body)
    if command != 2:
        raise ProtocolError('Expected object status command.')
    try:
        request = msgpack.unpackb(payload,raw=False,strict_map_key=False,
                                 max_map_len=32,max_array_len=64,max_str_len=512,max_bin_len=1024)
    except (ValueError, msgpack.UnpackException):
        raise ProtocolError('Invalid object status payload.') from None
    if (type(request) is not dict or 1 not in request
            or any(type(key) is not int or key not in range(1,12) for key in request)):
        raise ProtocolError('Invalid object status fields.')
    guid = request[1]
    if (type(guid) is not dict or set(guid) != {1} or type(next(iter(guid))) is not int
            or type(guid[1]) is not bytes or len(guid[1]) != 16 or guid[1] == bytes(16)):
        raise ProtocolError('Invalid object status GUID.')
    for key,dimensions in ((2,3),(3,4)):
        vector = request.get(key,{})
        if (type(vector) is not dict
                or any(type(field) is not int or field not in range(1,dimensions+1) for field in vector)
                or any(type(value) not in (int,float) or not math.isfinite(value) for value in vector.values())):
            raise ProtocolError('Invalid object status transform.')
    if (any(type(request.get(key,{})) is not dict for key in (4,5,6,8))
            or type(request.get(7,0)) is not int or not -(2**63) <= request.get(7,0) < 2**63
            or any(type(request.get(key,0)) is not int or not 0 <= request.get(key,0) < 2**32
                   for key in (9,10,11))):
        raise ProtocolError('Invalid object status data or sequence.')
    return request


def update_status_notification(request):
    return command_message(3,msgpack.packb(request,use_bin_type=True))


def create_enemy_request(body):
    command,payload = read_command_message(body)
    if command != 12:
        raise ProtocolError('Expected enemy creation command.')
    try:
        request = msgpack.unpackb(payload,raw=False,strict_map_key=False,
                                 max_map_len=5,max_array_len=0,max_str_len=512,max_bin_len=16)
    except (ValueError, msgpack.UnpackException):
        raise ProtocolError('Invalid enemy creation payload.') from None
    if (type(request) is not dict or any(type(key) is not int or key not in range(1,6) for key in request)
            or any(key not in request for key in (1,2,3,4))):
        raise ProtocolError('Invalid enemy creation fields.')
    guid = request[1]
    if (type(guid) is not dict or set(guid) != {1} or type(next(iter(guid))) is not int
            or type(guid[1]) is not bytes or len(guid[1]) != 16 or guid[1] == bytes(16)):
        raise ProtocolError('Invalid enemy object GUID.')
    for key,dimensions in ((2,3),(3,4)):
        vector = request[key]
        if (type(vector) is not dict
                or any(type(field) is not int or field not in range(1,dimensions+1) for field in vector)
                or any(type(value) not in (int,float) or not math.isfinite(value) for value in vector.values())):
            raise ProtocolError('Invalid enemy object transform.')
    if type(request[4]) is not str or not request[4] or type(request.get(5,'')) is not str:
        raise ProtocolError('Invalid enemy identity or recipient.')
    return request | {5:request.get(5,'')}


def create_enemy_notification(request):
    return command_message(13,msgpack.packb(request,use_bin_type=True))


def character_data_payload(character_data):
    """Validate the server snapshot against native CharacterData fields."""
    if (type(character_data) is not dict or set(character_data) != set(range(1,11))
            or any(type(key) is not int for key in character_data)):
        raise ProtocolError('Invalid authoritative character fields.')
    for key in (1,2,3):
        # The normal UserCharacter constructor leaves CharacterName null.
        # Native Write omits null references with skip-defaults, or writes nil.
        if key == 3 and character_data[key] is None:
            continue
        if type(character_data[key]) is not str or len(character_data[key].encode('utf-8')) > 512:
            raise ProtocolError('Invalid authoritative character text.')
    for key,bits in ((4,32),(5,64),(6,32),(7,32)):
        value = character_data[key]
        if type(value) is not int or not -(2**(bits-1)) <= value < 2**(bits-1):
            raise ProtocolError('Invalid authoritative character integer.')
    for key in (8,9,10):
        values = character_data[key]
        if (type(values) is not list or len(values) > 32
                or any(type(value) is not str or len(value.encode('utf-8')) > 512 for value in values)):
            raise ProtocolError('Invalid authoritative character equipment list.')
    return copy.deepcopy(character_data)


def create_player_request(body, player, character_data):
    """Decode native command 10 using authoritative player/character snapshots.

    character_data is the server-built numeric CharacterData map, not an HTTP
    request value. Omitted default fields are merged before comparison.
    """
    character_data = character_data_payload(character_data)
    command,request_id,payload = read_rpc_request(body)
    if command != 10:
        raise ProtocolError('Expected player creation RPC.')
    try:
        request = msgpack.unpackb(payload,raw=False,strict_map_key=False,
                                 max_map_len=16,max_array_len=32,max_str_len=512,max_bin_len=16)
    except (ValueError, msgpack.UnpackException):
        raise ProtocolError('Invalid player creation payload.') from None
    if (type(request) is not dict or any(type(key) is not int or key not in range(1,8) for key in request)
            or any(key not in request for key in (1,2,3,4,6))):
        raise ProtocolError('Invalid player creation fields.')
    guid = request[1]
    if (type(guid) is not dict or set(guid) != {1} or type(next(iter(guid))) is not int
            or type(guid[1]) is not bytes or len(guid[1]) != 16 or guid[1] == bytes(16)):
        raise ProtocolError('Invalid player object GUID.')
    for key,dimensions in ((2,3),(3,4)):
        vector = request[key]
        if (type(vector) is not dict
                or any(type(field) is not int or field not in range(1,dimensions+1) for field in vector)
                or any(type(value) not in (int,float) or not math.isfinite(value) for value in vector.values())):
            raise ProtocolError('Invalid player object transform.')
    defaults = {1:'',2:'',3:None,4:0,5:0,6:0,7:0,8:[],9:[],10:[]}
    actual = request[4]
    expected_player = player_payload(player)
    normalized = defaults | actual if type(actual) is dict else None
    if (type(character_data) is not dict or set(character_data) != set(defaults)
            or type(actual) is not dict
            or any(type(key) is not int or key not in defaults for key in actual)
            or any(normalized[key] != value for key,value in character_data.items() if key not in (6,7))
            or any(type(normalized[key]) is not int or not 0 <= normalized[key] <= character_data[key]
                   for key in (6,7))
            or any(type(value) is not type(character_data[key]) for key,value in actual.items())):
        raise ProtocolError('Character data differs from authoritative player.')
    supplied_player = request[6]
    if (type(supplied_player) is not dict
            or any(type(key) is not int or key not in expected_player for key in supplied_player)
            or any(value != expected_player[key] or type(value) is not type(expected_player[key])
                   for key,value in supplied_player.items())
            or supplied_player.get(1) != player['UserId']):
        raise ProtocolError('Player creation identity or statistics mismatch.')
    if type(request.get(5,0)) is not int or not -(2**31) <= request.get(5,0) < 2**31:
        raise ProtocolError('Invalid player creation type.')
    if type(request.get(7,'')) is not str:
        raise ProtocolError('Invalid player creation recipient.')
    result = copy.deepcopy(request)
    result.update({4:copy.deepcopy(character_data | {key:normalized[key] for key in (6,7)}),5:request.get(5,0),
                   6:expected_player,7:request.get(7,'')})
    return request_id,result


def create_player_reply(player):
    return msgpack.packb({1:player_payload(player)},use_bin_type=True)


def create_player_notification(request):
    return command_message(11,msgpack.packb(request,use_bin_type=True))


def load_status_request(body, account_id):
    command,payload = read_command_message(body)
    if command != 18:
        raise ProtocolError('Expected battle load status request.')
    try:
        request = msgpack.unpackb(payload,raw=False,strict_map_key=False,
                                 max_map_len=2,max_array_len=0,max_str_len=128,max_bin_len=0)
    except (ValueError, msgpack.UnpackException):
        raise ProtocolError('Invalid battle load status payload.') from None
    if (type(request) is not dict
            or any(type(key) is not int or key not in (1,2) for key in request)
            or type(request.get(1)) is not str or request[1] != account_id):
        raise ProtocolError('Invalid battle load status identity.')
    status = request.get(2,0)
    if type(status) is not int or not -(2**31) <= status < 2**31:
        raise ProtocolError('Invalid battle load status integer.')
    return status


def load_status_notification(account_id, status):
    if type(account_id) is not str or not account_id or len(account_id) > 128:
        raise ProtocolError('Invalid battle load status identity.')
    if type(status) is not int or not -(2**31) <= status < 2**31:
        raise ProtocolError('Invalid battle load status integer.')
    return command_message(19,msgpack.packb({1:account_id,2:status},use_bin_type=True))
