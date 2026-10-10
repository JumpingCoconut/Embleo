"""Preflight the native event image paths against installed manifest names."""

import re


class EventResources:
    def __init__(self, names, languages):
        if (type(names) not in (list,tuple,set,frozenset)
                or any(type(name) is not str or not name for name in names)
                or type(languages) not in (list,tuple) or not languages
                or any(type(language) is not str or not re.fullmatch('[a-z]{2}',language)
                       for language in languages)):
            raise ValueError('Installed manifest names and explicit client languages required.')
        self.names = frozenset(name.lower() for name in names)
        self.languages = tuple(dict.fromkeys(languages))

    def __call__(self, event):
        if type(event) is not dict:
            raise ValueError('Event metadata required.')
        for field in ('EventId','LogoId','DecoId'):
            value = event.get(field)
            if (type(value) is not str or not re.fullmatch('[A-Za-z0-9_]*',value)
                    or field == 'EventId' and not value):
                raise ValueError('Invalid native event image identity.')
        paths = ['UIExternal/UI/Common/Textures/Icon/PvE/'+event['EventId']]
        if event['LogoId']:
            paths.extend(f'lang_{language}/Textures/Icon/PvE/pve_{language}_{event["LogoId"]}'
                         for language in self.languages)
        if event['DecoId']:
            # EpisodeDetailInfo: contents/reward panels and localized header.
            paths.extend(f'UIExternal/UI/Common/Textures/Icon/PvE/{event["DecoId"]}/'
                         f'{event["DecoId"]}_{suffix}' for suffix in ('01','02','03','05'))
            paths.extend(f'lang_{language}/Textures/Icon/PvE/pve_{language}_{event["DecoId"]}_04'
                         for language in self.languages)
        missing = [path for path in paths if path.lower() not in self.names]
        if missing:
            raise ValueError('Missing installed event images: '+', '.join(missing))
        return tuple(paths)
