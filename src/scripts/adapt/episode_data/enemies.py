def SerVec2toVec2(SerializableVector2):
	vector_2 = [
		SerializableVector2["x"],
		SerializableVector2["y"]
	]

	return vector_2


def SerVec3toVec3(SerializableVector3):
	vector_3 = [
		SerializableVector3["x"],
		SerializableVector3["y"],
		SerializableVector3["z"]
	]

	return vector_3

def episode_enemy_individual_ids(master_data):
	"""All placed, parent-child and generator individuals, in source order."""
	ids = []
	seen = set()
	for entry in master_data["Datas"]:
		candidates = [entry["_individualID"],
			*entry["_childEnemyData"]["EnemyIds"],
			entry["_summonEnemyData"]["EnemyId"]]
		for individual_id in candidates:
			if individual_id and individual_id not in seen:
				seen.add(individual_id)
				ids.append(individual_id)
	return ids


def adapt_episode_enemies_for_episode_layout(master_data, *, platoon_master_data=None):
	enemies = []
	formations = {entry["_id"]: entry
		for entry in (platoon_master_data or {"Datas": []})["Datas"]}

	# yeah, that's a lot of data
	for entry in master_data["Datas"]:
		layout_entry = {
			"EpisodeEnemyId": entry["_id"],
			"EnemyId": entry["_individualID"],
			"RoleType": entry["_enemyType"] + 1,  # 0 is Unknown and breaks enemy
			"Flags": 0,

			"AppearanceNum": entry["_appearanceNum"],
			"MaxAppearanceNum": entry["_appearanceNum"],

			"GroupId": entry["_groupID"],

			"AppearanceRule": {},
			"Child": {},
			"SummonRule": {},

			"VisualId": entry["_charactorVisualId"],  # Yes, charactor
			"SurviveId": entry["_surviveId"],

			"PatrolPoints": entry["_patrolPoints"],
			"PriorityPoint": entry["_priorityPoint"],

			"ScenarioNo": [entry["_startScenarioNo"], entry["_endScenarioNo"]]
		}

		# EpisodeEnemyAppearanceRule
		layout_entry["AppearanceRule"] = {
			"Type": entry["_appearanceID"],
			"Params": [entry["_appearanceParam1"]]
		}

		# EpisodeEnemyChild
		formation_id = entry["_childEnemyData"]["FormationId"]
		formation = formations.get(formation_id)
		if formation_id and formation is None:
			raise ValueError("Unknown platoon formation {!r} for episode enemy {!r}".format(
				formation_id, entry["_id"]))
		layout_entry["Child"] = {
			"Ids": entry["_childEnemyData"]["EnemyIds"],
			"Formation": formation["Formation"] if formation else "",
			"FormationPadding": SerVec2toVec2(formation["FormationPadding"])
				if formation else [0, 0]
		}

		# EpisodeEnemySummonRule
		layout_entry["SummonRule"] = {
			"EpisodeEnemyId": entry["_summonEnemyData"]["EnemyId"],
			"InitialAppearNum": entry["_summonEnemyData"]["_initialAppearNum"],
			"MinLimitNum": entry["_summonEnemyData"]["_minLimitNum"],
			"TotalNum": entry["_summonEnemyData"]["_totalNum"],
			"Offset": SerVec2toVec2(entry["_summonEnemyData"]["Offset"]),
			"Range": SerVec2toVec2(entry["_summonEnemyData"]["Range"]),
			"AppearPointName": entry["_summonEnemyData"]["AppearPointName"],
			"DieWithChild": bool(entry["_summonEnemyData"]["DieWithChild"]),
			"InitRotateAngle": entry["_summonEnemyData"]["InitRotateAngle"],
			"OffsetAdd": SerVec2toVec2(entry["_summonEnemyData"]["OffsetAdd"]),
			"RangeAdd": SerVec2toVec2(entry["_summonEnemyData"]["RangeAdd"]),
			"InitRotateAngleAdd": entry["_summonEnemyData"]["InitRotateAngleAdd"]
		}

		enemies.append(layout_entry)

	return enemies
