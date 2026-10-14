def adapt_debug_platoon_info(debug_data):
    adapted_platoon_data = {}

    for platoon_entry in debug_data["Datas"]:
        adapted_platoon_data[platoon_entry["_id"]] = platoon_entry

    return adapted_platoon_data
