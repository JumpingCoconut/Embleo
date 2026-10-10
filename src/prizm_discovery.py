"""Game.Net.Room HTTP view built from authoritative room/event/profile data.

Callers enforce event access and public/private/guild visibility before using
this view. Expiry units must come from the HTTP contract, not a monotonic
transport-credential deadline. This module does not publish events or routes.
"""

from copy import deepcopy


class CatalogRoomViews:
    """Combine installed difficulty links with scoped host display metadata.

    display(viewer, host, character) resolves IconUrl, EmblemId, IsFriend and
    IsGuild from server data. expires(room) supplies the verified wire expiry
    units; neither callback may trust submitted room/profile fields.
    """
    def __init__(self, catalog, display, expires):
        if not callable(display) or not callable(expires):
            raise ValueError('Room display and expiry readers required.')
        self.links = deepcopy(catalog.episodes.links)
        self.active_events = getattr(catalog,'active_event_ids',None)
        self.display = display
        self.expires = expires

    def __call__(self, account, room):
        if type(account) is not str or not account:
            raise ValueError('Authenticated room viewer required.')
        links = [row for row in self.links if row['EpisodeId'] == room['EpisodeId']]
        if 'EventId' in room:
            links = [row for row in links if (row['EventId'],row['Difficulty'])
                     == (room['EventId'],room['Difficulty'])]
        if self.active_events is not None:
            active = set(self.active_events())
            links = [row for row in links if row['EventId'] in active]
        if len(links) != 1:
            raise ValueError('Room episode must resolve to one catalog difficulty.')
        hosts = [player for player in room['Players'] if player.get('IsHost') is True]
        if len(hosts) != 1:
            raise ValueError('Room must contain one authoritative host.')
        host = hosts[0]
        metadata = self.display(account,host['UserId'],host['CharacterId'])
        if (type(metadata) is not dict
                or set(metadata) != {'IconUrl','EmblemId','IsFriend','IsGuild'}):
            raise ValueError('Complete host display metadata required.')
        link = links[0]
        return room_view(room,link['RequiredPower'],link['Difficulty'],
            metadata['IconUrl'],metadata['EmblemId'],metadata['IsFriend'],metadata['IsGuild'],
            self.expires(deepcopy(room)))


def room_access(room, route, viewer_guild, host_guild):
    """Emulator access policy using server-resolved guilds, never client flags.

    Native enums establish values, not backend policy: private rooms permit
    direct-ID admission only; guild rooms require current shared membership.
    Apply this again inside admission, not only while constructing a list.
    """
    if type(route) is not int or route not in (1,2,3):
        return False
    level = room.get('PublicLevel')
    if type(level) is not int:
        return False
    if level == 1:
        return True
    if level == 2:
        return route == 3
    if level == 3:
        return (type(viewer_guild) is str and bool(viewer_guild)
                and type(host_guild) is str and viewer_guild == host_guild)
    return False


def room_view(room, required_power, difficulty, icon_url, emblem_id,
              is_friend, is_guild, expire_at):
    for value in (required_power,difficulty):
        if type(value) is not int or not 0 <= value < 2**31:
            raise ValueError('Invalid room event integer.')
    if type(expire_at) is not int or not 0 <= expire_at < 2**63:
        raise ValueError('Invalid room expiry.')
    if type(is_friend) is not bool or type(is_guild) is not bool:
        raise ValueError('Invalid room relationship flags.')
    if type(icon_url) is not str or type(emblem_id) is not str:
        raise ValueError('Invalid host profile display fields.')
    for field in ('RoomId','EpisodeId'):
        if type(room.get(field)) is not str or not room[field]:
            raise ValueError('Invalid room identity.')
    players = room.get('Players')
    if type(players) is not list or not players:
        raise ValueError('Room must contain players.')
    hosts = [player for player in players if player.get('IsHost') is True]
    if len(hosts) != 1:
        raise ValueError('Room must contain exactly one host.')
    host = hosts[0]
    for field in ('UserId','CharacterId','Name'):
        if type(host.get(field)) is not str or (field != 'CharacterId' and not host[field]):
            raise ValueError('Invalid host identity.')
    level = host.get('CharacterLevel')
    if type(level) is not int or not 0 <= level < 2**31:
        raise ValueError('Invalid host level.')
    return dict(RoomId=room['RoomId'],EpisodeId=room['EpisodeId'],
                RequiredPower=required_power,Difficulty=difficulty,
                HostUserId=host['UserId'],HostCharacterId=host['CharacterId'],
                HostName=host['Name'],HostLevel=level,IconUrl=icon_url,
                EmblemId=emblem_id,Count=len(players),IsFriend=is_friend,
                IsGuild=is_guild,ExpireAt=expire_at)
