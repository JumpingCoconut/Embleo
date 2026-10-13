from .items import adapt_item_records


def adapt_breakables_for_episode_layout(debug_data):
    breakables = []

    for entry in debug_data["Datas"]:
        layout_entry = {
            "EpisodeBreakableId": entry["_id"],
            "ResourceId": entry["_masterID"]
        }

        breakables.append(dict.copy(layout_entry))

    return breakables


def adapt_breakable_items_for_episode_layout(debug_data):
    # Game.Net.EpisodeItem carries the spawn data consumed by
    # App.Data.EpisodeBreakableInfo.Setup. ItemDropMethod.Breakable is 2.
    return adapt_item_records(debug_data, 2)
