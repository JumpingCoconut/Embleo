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

    clip_counter = 0
    for clip in move_track["clips"]:
        # print(clip)

        if clip["behaviour"]["m_Name"] in MOVE_CLIPS:
            MoveSetting["totalMoveCount"] += 1
            MoveSetting["moveCount"].append(clip_counter)
            MoveSetting["direction"].append(clip["behaviour"]["direction"])
            MoveSetting["speed"].append(clip["behaviour"]["speed"])

            clip_counter += 1

    return MoveSetting
