"""Assemble installed raid providers for the HTTP host's runtime factory."""

from copy import deepcopy
from pve_preparation import installed_battle_assembler


def installed_runtime_factory(capacity, data_root, database, ordering,
                              definitions, base_visuals, event_catalog,
                              *, eligibility_provider, room_settings_provider,
                              room_view_provider, player_provider,
                              connection_provider, guild_provider=None,
                              minion_provider=None, master_group=None,
                              extra_saves=(), level_overrides=None,
                              listener_limits=None, completion_provider=None):
    """Prepare installed data now; create Runtime only on its owning loop.

    Operator config supplies verified event metadata, account readers and
    public connection information. No endpoints, schedules or player data are
    invented here. Configuring this factory does not start a listener.
    Definitions may use unique native episode keys, or event-link keys with
    an explicit canonical EpisodeId when difficulties share an arena.
    """
    if type(capacity) is not int or not 1 <= capacity <= 32:
        raise ValueError('Invalid raid capacity.')
    providers = dict(eligibility_provider=eligibility_provider,
        room_settings_provider=room_settings_provider,room_view_provider=room_view_provider,
        player_provider=player_provider,connection_provider=connection_provider)
    if not callable(ordering) or any(not callable(provider) for provider in providers.values()):
        raise ValueError('Complete account-scoped raid providers required.')
    for provider in (guild_provider,minion_provider,level_overrides,completion_provider):
        if provider is not None and not callable(provider):
            raise ValueError('Invalid optional raid provider.')
    linked = {row['EpisodeId'] for row in event_catalog.episodes.links}
    bindings = {row['EpisodePveEventId'] for row in event_catalog.episodes.links}
    if (not linked or type(definitions) is not dict
            or set(definitions) not in (linked,bindings)
            or any(type(row) is not dict for row in definitions.values())):
        raise ValueError('Raid catalog and installed episode definitions must agree.')
    bound = set(definitions) == bindings and bindings != linked
    if bound and any(definitions[row['EpisodePveEventId']].get('EpisodeId') != row['EpisodeId']
                     for row in event_catalog.episodes.links):
        raise ValueError('Raid binding definition must match its canonical native episode.')
    assembler = installed_battle_assembler(data_root,database,ordering,
        deepcopy(definitions),deepcopy(base_visuals),master_group,extra_saves,level_overrides)
    def validate_participant(room, prepared, character_id, overrides):
        eligibility = eligibility_provider(prepared.account_id)
        power = prepared.character(prepared.account_id,character_id,overrides)['Power']
        context = event_catalog.eligible_event(room.get('EpisodePveEventId',room['EpisodeId']),power,
                                               eligibility['Platform'],eligibility['ClientVersion'])
        if 'EventId' in room and context != (room['EventId'],room['Difficulty']):
            raise ValueError('Prepared room event is no longer eligible.')
    assembler.eligibility_validator = validate_participant
    preflight = ([{'EpisodeId':row['EpisodeId'],'EpisodePveEventId':row['EpisodePveEventId'],
                   'BattleId':'preflight'} for row in event_catalog.episodes.links] if bound else
                 [{'EpisodeId':episode_id,'BattleId':'preflight'} for episode_id in sorted(linked)])
    for room in preflight:
        assembler.response_builder.for_room(room)
    limits = deepcopy(listener_limits or {})

    def factory():
        from prizm_runtime import Runtime
        return Runtime(capacity,event_catalog=event_catalog,battle_provider=assembler,
                       guild_provider=guild_provider,battle_minion_provider=minion_provider,
                       completion_provider=completion_provider,
                       **providers,**limits)

    return factory
