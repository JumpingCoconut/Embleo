import os
import json

item_data_sources = {
    "EpisodeBreakableMasterDataObject": 2
}


def adapt_items_for_episode_layout(episode_master_data_folder_path):
    items = []

    for file_name, drop_type in item_data_sources.items():

        file_path = episode_master_data_folder_path + file_name + ".json"

        if os.path.exists(file_path):

            with open(file_path, "r", encoding="UTF-8") as f:

                debug_data = json.load(f)

                for entry in debug_data["Datas"]:
                    adapted_item = {
                        "EpisodeItemId": entry["_id"],
                        "ItemDropMethod": drop_type,
                        "DropResourceId": entry["_masterID"],
                        "ObjectCount": entry["_stackNum"],
                        "ParallelNum": entry["_parallelNum"],
                        "EpisodeEvent": None,
                        "ScenarioNo": [entry["_startScenarioNo"], entry["_endScenarioNo"]]
                    }

                    items.append(adapted_item)

    return items
