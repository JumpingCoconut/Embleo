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

def adapt_episode_enemies_for_episode_layout(master_data):
	enemies = []

	# yeah, that's a lot of data
	for entry in master_data["Datas"]:
		layout_entry = {
			"EpisodeEnemyId": entry["_id"],
			"EnemyId": entry["_individualID"],
			"RoleType": entry["_enemyType"] + 1,  # 0 is Unknown and breaks enemy
			# "Flags": 0,

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
			"Params": [entry["_appearanceParam1"], str(entry["_appearanceIntParam1"])]
		}

		# EpisodeEnemyChild
		layout_entry["Child"] = {
			"Ids": entry["_childEnemyData"]["EnemyIds"],
			"Formation": entry["_childEnemyData"]["FormationId"],
			"FormationPadding": SerVec2toVec2({"x": 1.0, "y": 1.0})
		}

		if entry["_childEnemyData"]["FormationId"] == "3_1":
			layout_entry["Child"]["Formation"] = "1,,,,1,\r\n,\r\n,,0,\r"

		summon_data = entry["_summonEnemyData"]

		# EpisodeEnemySummonRule
		layout_entry["SummonRule"] = {
			"EpisodeEnemyId": summon_data["EnemyId"],
			"InitialAppearNum": summon_data["_initialAppearNum"],
			"MinLimitNum": summon_data["_minLimitNum"],
			"TotalNum": summon_data["_totalNum"],
			"Offset": SerVec2toVec2(summon_data["Offset"]),
			"Range": SerVec2toVec2(summon_data["Range"]),
			"AppearPointName": summon_data["AppearPointName"],
			"DieWithChild": bool(summon_data["DieWithChild"]),
			"InitRotateAngle": summon_data["InitRotateAngle"],
			"OffsetAdd": SerVec2toVec2(summon_data["OffsetAdd"]),
			"RangeAdd": SerVec2toVec2(summon_data["RangeAdd"]),
			"InitRotateAngleAdd": summon_data["InitRotateAngleAdd"]
		}

		enemies.append(layout_entry)

	for entry in enemies:

		if entry["SummonRule"]["EpisodeEnemyId"] != "":
			print(entry)

	return enemies
