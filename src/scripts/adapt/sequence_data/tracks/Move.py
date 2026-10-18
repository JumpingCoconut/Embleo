from .indexed import put_clip, indexed_data


MOVE_CLIPS = [
    "Move Clip",
    "DodgingMove Clip",
    "EnemyMove Clip"
]


def adapt_move_track(move_track, sequence_name, owner_id):
    MoveSetting = {
        "id": owner_id,
        "sequenceName": sequence_name,
        "totalMoveCount": 0,
        "moveCount": [],
        "direction": [],
        "speed": []
    }

    # print(action["action_name"])

    clips = {}
    for clip in move_track["clips"]:
        # print(clip)

        if clip["behaviour"]["m_Name"] in MOVE_CLIPS:
            data = clip['behaviour']
            index = data.get('clipIndex', len(clips))
            put_clip(clips, index, {'direction': data['direction'], 'speed': data['speed']})

    values = indexed_data(clips)
    MoveSetting['totalMoveCount'] = len(values)
    MoveSetting['moveCount'] = list(range(len(values)))
    MoveSetting['direction'] = [v.get('direction', dict(x=0, y=0, z=0)) for v in values]
    MoveSetting['speed'] = [v.get('speed', 0) for v in values]
    return MoveSetting
