"""Native-verified numeric MessagePack lobby payloads.

AppPlayer.Write 0x3280BBC: fields 1..16. JoinReply.Write 0x1B63BD8:
players/suspend-time/count/one-time-limit fields 1..4. RoomInfoReply.Write
0x36AF840: players/room/private/mode/status/public-level fields 1..6.
NetUID and UserView are runtime fields, not serialized AppPlayer fields.
"""

import msgpack
from prizm_protocol import read_rpc_request, rpc_response, command_message


class LobbyService:
    """Dispatch room RPCs using a server-owned, authorized room snapshot.

    The provider must atomically validate admission and return current players.
    It receives the connection identity, never a client-supplied room ID.
    """

    def __init__(self, room_provider):
        self.room_provider = room_provider

    def __call__(self, session, service, body, reliable):
        if not reliable or service != 1000:
            raise ValueError('Unsupported lobby service or delivery mode.')
        command, request_id, payload = read_rpc_request(body)
        try:
            request = msgpack.unpackb(payload, raw=False, strict_map_key=False,
                                      max_map_len=32, max_array_len=32,
                                      max_str_len=1024, max_bin_len=1024)
            if not isinstance(request, dict) or any(type(key) is not int for key in request):
                raise ValueError('Invalid lobby request map.')
            if command == 1:
                if any(key != 1 for key in request) or type(request.get(1, False)) is not bool:
                    raise ValueError('Invalid rejoin request.')
            elif command == 12:
                if request:
                    raise ValueError('Room-info request must be empty.')
            else:
                return [(service, rpc_response(command, request_id, b'Unsupported room command.', status=2), True)]
            room = self.room_provider(session, command, request.get(1, False))
            if room['RoomId'] != session.admission.room_id:
                raise ValueError('Room admission mismatch.')
            if session.admission.account_id not in {player['UserId'] for player in room['Players']}:
                raise ValueError('Player is not admitted to the room.')
            if command == 1:
                reply = join_reply(room['Players'], room['LimitSuspendTime'],
                                   room['LimitSuspendCount'], room['OnetimeLimitSuspendTime'])
            else:
                reply = room_info_reply(room['Players'], room['RoomId'], room['IsPrivate'],
                                        room['Mode'], room['Status'], room['PublicLevel'])
        except (ValueError, KeyError, TypeError, msgpack.UnpackException):
            # Do not include request contents, player data or credentials in errors.
            return [(service, rpc_response(command, request_id, b'Invalid or unavailable room request.', status=2), True)]
        return [(service, rpc_response(command, request_id, reply), True)]


PLAYER_FIELDS = (
    ('UserId', str), ('Name', str), ('CharacterId', str),
    ('CharacterLevel', int), ('CharacterPower', int),
    ('VisualEquipments', list), ('Order', int), ('IsHost', bool),
    ('CliVersion', str), ('Ready', int), ('CostumeSpells', list),
    ('WeaponSpells', list), ('CharacterHp', int), ('CharacterAttack', int),
    ('CharacterDefense', int), ('MissionRank', int))


def player_payload(player, *, allow_unselected=False):
    """Require server-owned profile/stat inputs rather than invent battle stats."""
    result = {}
    for number, (name, kind) in enumerate(PLAYER_FIELDS, 1):
        value = player.get(name)
        if type(value) is not kind:
            raise ValueError('Invalid player field: ' + name)
        if kind is int and not -(2**31) <= value < 2**31:
            raise ValueError('Player integer out of range: ' + name)
        if kind is list and any(type(item) is not str for item in value):
            raise ValueError('Player array must contain strings: ' + name)
        result[number] = list(value) if kind is list else value
    if not result[1]:
        raise ValueError('Player and character identifiers are required.')
    if not result[3]:
        if (not allow_unselected or any(result[key] != 0 for key in (4,5,10,13,14,15))
                or any(result[key] for key in (6,11,12))):
            raise ValueError('Unselected lobby player must have empty character state.')
    return result


def _players(players):
    result = [player_payload(player,allow_unselected=True) for player in players]
    if any(player[7] < 1 for player in result):
        raise ValueError('Room player order must be one-based.')
    if len({player[1] for player in result}) != len(result):
        raise ValueError('Duplicate room player.')
    if len({player[7] for player in result}) != len(result):
        raise ValueError('Duplicate player order.')
    if result and sum(player[8] for player in result) != 1:
        raise ValueError('A populated room must have exactly one host.')
    return result


def _int(value):
    if type(value) is not int or not 0 <= value < 2**31:
        raise ValueError('Invalid lobby integer.')
    return value


def join_reply(players, suspend_time, suspend_count, one_time_suspend):
    return msgpack.packb({1: _players(players), 2: _int(suspend_time),
                         3: _int(suspend_count), 4: _int(one_time_suspend)}, use_bin_type=True)


def room_info_reply(players, room_id, private, mode, status, public_level):
    if type(room_id) is not str or not room_id or type(private) is not bool:
        raise ValueError('Invalid room identity or privacy flag.')
    return msgpack.packb({1: _players(players), 2: room_id, 3: private,
                         4: _int(mode), 5: _int(status), 6: _int(public_level)}, use_bin_type=True)


def ready_notification(user_id, ready):
    # ReadyRequest is command 7; ReadyNotification is command 8. The latter
    # is verified by the native receive jump table at 0x3BE3998.
    if type(user_id) is not str or not user_id:
        raise ValueError('Invalid readiness player.')
    body = msgpack.packb({1:user_id,2:_int(ready)},use_bin_type=True)
    return command_message(8,body)


def join_notification(player):
    # JoinNotification.Write at 0x1B6358C: field 1 is AppPlayer.
    return command_message(2,msgpack.packb({1:player_payload(player,allow_unselected=True)},use_bin_type=True))


def character_change_notification(player):
    return command_message(6,msgpack.packb({1:player['UserId'],2:player_payload(player)},use_bin_type=True))


def leave_notification(user_id, players):
    # LeaveNotification.Write at 0x1B65A78: field 1 is UserId;
    # field 2 is the authoritative AppPlayer array after host handover.
    if type(user_id) is not str or not user_id:
        raise ValueError('Invalid departing player.')
    return command_message(4,msgpack.packb({1:user_id,2:_players(players)},use_bin_type=True))


def in_game_start_notification(user_id):
    # InGameStartNotification.Write at 0x1B628DC serializes UserId as field 1.
    # Command 10 is selected by the room-service receive table at 0x3BE3998.
    if type(user_id) is not str or not user_id:
        raise ValueError('Invalid starting player.')
    return command_message(10,msgpack.packb({1:user_id},use_bin_type=True))
