"""Account-scoped publication of configured raid events and home tiles."""

from copy import deepcopy
from datetime import datetime,timezone


def scheduled_event_metadata(event, catalog, *, ranking_start, ranking_end, ranking_confirm):
    """Render one configured event's UTC wire dates from its admission schedule.

    Ranking dates are explicit operator policy, independent of battle admission.
    This does not supply image identities, reward rules or other event fields.
    """
    if type(event) is not dict or type(event.get('EventId')) is not str:
        raise ValueError('Configured event identity required.')
    dates = catalog.events.get(event['EventId'])
    if dates is None:
        raise ValueError('Event has no admission schedule.')
    ranking = (ranking_start,ranking_end,ranking_confirm)
    all_dates = (*dates,*ranking)
    if any(not isinstance(value,datetime) or value.utcoffset() is None for value in all_dates):
        raise ValueError('Timezone-aware event dates required.')
    if not ranking_start <= ranking_end <= ranking_confirm:
        raise ValueError('Invalid ranking display window.')
    fields = ('PublishStartAt','StartAt','EndAt','RankingStartAt','RankingEndAt','RankingConfirmAt')
    result = deepcopy(event)
    result.update({field:value.astimezone(timezone.utc).isoformat().replace('+00:00','Z')
                   for field,value in zip(fields,all_dates)})
    return result


class EventPublication:
    """Metadata/resources must be validated by installed configuration policy.

    account_event supplies each account's points, episode and ranking state.
    The schedule catalog controls visibility; publication does not grant room
    admission, which still uses the separate active-window eligibility gate.
    """
    def __init__(self, catalog, events, account_event, *, resource_validator=None):
        self.catalog = catalog
        self.events = {}
        self.account_event = account_event
        if resource_validator is not None and not callable(resource_validator):
            raise ValueError('Invalid event resource validator.')
        for event in events:
            key = event.get('EventId')
            if type(key) is not str or not key or key in self.events:
                raise ValueError('Invalid or duplicate event publication identity.')
            if resource_validator is not None:
                resource_validator(deepcopy(event))
            self.events[key] = deepcopy(event)

    def event_list(self):
        return [deepcopy(self.events[key]) for key in self.catalog.published_event_ids()
                if key in self.events]

    def selected(self, account, event_id):
        if type(account) is not str or not account or type(event_id) is not str or event_id not in {
                event['EventId'] for event in self.event_list()}:
            raise ValueError('Event is not published.')
        value = deepcopy(self.account_event(account, event_id))
        if type(value) is not dict or value.get('EventId') != event_id:
            raise ValueError('Invalid account event publication.')
        return value

    def apply_top(self, account, top):
        events = self.event_list()
        pve = [self.selected(account,event['EventId']) for event in events]
        result = deepcopy(top)
        ids = set(self.events)
        result['events'] = [row for row in result.get('events',[]) if row.get('EventId') not in ids] + events
        result['pveEvents'] = [row for row in result.get('pveEvents',[]) if row.get('EventId') not in ids] + pve
        tiles = [tile for tile in result.get('orderdIds',[]) if not (
            tile.get('Type') == 3 and tile.get('MasterDataId') in ids)]
        result['orderdIds'] = tiles
        for event in events:
            tile = {'MasterDataId':event['EventId'], 'Type':3}
            if tile not in tiles:
                tiles.append(tile)
        return result
