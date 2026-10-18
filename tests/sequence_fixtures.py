"""Small fixtures for exercising the shared sequence adapters."""
from scripts.adapt.sequence_data.adapt_sequence import adapt_sequence_timeline, get_sequence_timeline_data


def wrappers(adapted):
    return [{category: [adapted[category]]} for category in
            ('AttackSetting', 'UpdateParameterSetting', 'MoveSetting', 'ResourceList')
            if adapted[category]]


def adapt_clips(owner, sequence, resolve):
    tracks = {}
    for track in sequence['tracks']:
        for reference in track['clips']:
            clip = resolve(reference['behaviourPrefab'])
            name = clip['m_Name']
            if name == 'Animator Clip':
                category = 'Animator Track'
            elif name == 'Move Clip':
                category = 'Move Track'
            elif name in ('SpecialSkillMagic Clip', 'UpdateAttackInfo Clip'):
                category = 'UpdateParameter Track'
            elif name in ('EffectCall Clip', 'SoundCall Clip', 'VoiceCall Clip'):
                category = 'EffectCall Track'
            else:
                category = 'Attack Track'
            tracks.setdefault(category, {'behaviour': {'m_Name': category}, 'clips': []})['clips'].append(
                {'behaviour': clip})
    return wrappers(adapt_sequence_timeline({'action_name': sequence['m_Name'], 'tracks': list(tracks.values())}, owner))


def adapt_bundle(path, owner):
    import UnityPy
    env = UnityPy.load(str(path))
    roots = [(obj.path_id, obj.read_typetree()) for obj in env.objects
             if obj.type.name == 'MonoBehaviour']
    roots = [(path_id, data) for path_id, data in roots if 'tracks' in data]
    assert len(roots) == 1
    path_id, data = roots[0]
    timeline = get_sequence_timeline_data(env, path_id, data['m_Name'], owner)
    return wrappers(adapt_sequence_timeline(timeline, owner))
