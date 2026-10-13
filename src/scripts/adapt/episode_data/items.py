import os
import json
from pathlib import Path

item_data_sources = {
    "EpisodeBreakableMasterDataObject": 2
}


def adapt_item_records(debug_data, drop_type):
    return [
        {
            "EpisodeItemId": entry["_id"],
            "ItemDropMethod": drop_type,
            "DropResourceId": entry["_masterID"],
            "ObjectCount": entry["_stackNum"],
            "ParallelNum": entry["_parallelNum"],
            "EpisodeEvent": None,
            "ScenarioNo": [entry["_startScenarioNo"], entry["_endScenarioNo"]]
        }
        for entry in debug_data["Datas"]
    ]


def adapt_items_for_episode_layout(episode_master_data_folder_path):
    items = []

    for file_name, drop_type in item_data_sources.items():

        file_path = Path(episode_master_data_folder_path) / (file_name + ".json")

        if os.path.exists(file_path):

            with open(file_path, "r", encoding="UTF-8") as f:

                debug_data = json.load(f)

                items.extend(adapt_item_records(debug_data, drop_type))

    return items
