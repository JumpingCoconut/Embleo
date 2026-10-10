"""Validated event difficulty links and server-owned admission eligibility.

This is not event publication: display resources, schedules and per-account
event state must be supplied before the HTTP discovery routes can expose it.
"""

import copy
import re
from datetime import datetime, timezone


def _version(value):
    if type(value) is not str or not re.fullmatch(r'\d+\.\d+\.\d+',value):
        raise ValueError('Expected a numeric three-part client version.')
    return tuple(int(part) for part in value.split('.'))


class EpisodeCatalog:
    def __init__(self, links, installed_episode_ids):
        self.links = copy.deepcopy(links)
        seen = set()
        for row in self.links:
            for field in ('EpisodePveEventId','EventId','EpisodeId'):
                if type(row.get(field)) is not str or not row[field]:
                    raise ValueError('Invalid event episode identity.')
            if row['EpisodePveEventId'] in seen or row['EpisodeId'] not in installed_episode_ids:
                raise ValueError('Duplicate event link or uninstalled episode.')
            seen.add(row['EpisodePveEventId'])
            for field in ('RequiredPower','Difficulty'):
                if type(row.get(field)) is not int or not 0 <= row[field] < 2**31:
                    raise ValueError('Invalid event episode integer.')
            for field in ('MinVerIOS','MinVerAndroid'):
                _version(row[field])

    def episode_scope(self, event_id, difficulty, power, platform, version):
        if (type(event_id) is not str or not event_id
                or type(difficulty) is not int or difficulty < 0
                or type(power) is not int or power < 0
                or platform not in ('android','ios')):
            raise ValueError('Invalid server eligibility input.')
        client = _version(version)
        minimum_field = 'MinVerAndroid' if platform == 'android' else 'MinVerIOS'
        return tuple(dict.fromkeys(row['EpisodeId'] for row in self.links
            if row['EventId'] == event_id and row['Difficulty'] == difficulty
            and power >= row['RequiredPower'] and client >= _version(row[minimum_field])))


class ScheduledCatalog:
    """Internal UTC schedule gate; dates are aware datetimes, not wire strings.

    Publication can precede battles. Admission uses [StartAt, EndAt); ranking
    visibility after EndAt is separate and is not removed by this class.
    """
    def __init__(self, episodes, events, clock=lambda: datetime.now(timezone.utc)):
        self.episodes = episodes
        self.clock = clock
        self.events = {}
        for event in events:
            event_id = event.get('EventId')
            if type(event_id) is not str or not event_id or event_id in self.events:
                raise ValueError('Invalid or duplicate event schedule.')
            dates = []
            for field in ('PublishStartAt','StartAt','EndAt'):
                value = event.get(field)
                if not isinstance(value,datetime) or value.utcoffset() is None:
                    raise ValueError('Event dates must include a timezone.')
                dates.append(value.astimezone(timezone.utc))
            if not dates[0] <= dates[1] < dates[2]:
                raise ValueError('Invalid publication or battle window.')
            self.events[event_id] = tuple(dates)
        if any(row['EventId'] not in self.events for row in episodes.links):
            raise ValueError('Episode link has no event schedule.')

    def _now(self):
        value = self.clock()
        if not isinstance(value,datetime) or value.utcoffset() is None:
            raise ValueError('Event clock must include a timezone.')
        return value.astimezone(timezone.utc)

    def published_event_ids(self):
        now = self._now()
        return tuple(event_id for event_id,dates in self.events.items() if dates[0] <= now)

    def active_event_ids(self):
        """Battle windows, excluding historical ranking/publication entries."""
        now = self._now()
        return tuple(event_id for event_id,dates in self.events.items()
                     if dates[1] <= now < dates[2])

    def episode_scope(self, event_id, difficulty, power, platform, version):
        dates = self.events.get(event_id)
        now = self._now()
        if dates is None or not dates[1] <= now < dates[2]:
            return ()
        return self.episodes.episode_scope(event_id,difficulty,power,platform,version)

    def eligible_event(self, episode_id, power, platform, version):
        matches = set()
        for row in self.episodes.links:
            if row['EpisodeId'] == episode_id and episode_id in self.episode_scope(
                    row['EventId'],row['Difficulty'],power,platform,version):
                matches.add((row['EventId'],row['Difficulty']))
        if len(matches) != 1:
            raise ValueError('Episode must resolve to one active eligible event.')
        return next(iter(matches))
