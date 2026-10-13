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


def generate_external_enemies(adapted_enemy):
	external_enemies = []

	external_enemy_individual_id_list = []

	if adapted_enemy["RoleType"] == 2:  # Parent
		external_enemy_individual_id_list = adapted_enemy["Child"]["Ids"]
	elif adapted_enemy["RoleType"] == 3:  # Generator
		external_enemy_individual_id_list.append(adapted_enemy["SummonRule"]["EpisodeEnemyId"])

	for individual_id in external_enemy_individual_id_list:
		# Must follow this naming scheme
		external_id = "Ext.{}.{}".format(adapted_enemy["EpisodeEnemyId"], individual_id)

		if individual_id == "":
			print("Tried to generate an external enemy with no EnemyId", external_id)
			continue

		external_enemy = {
			"EpisodeEnemyId": external_id,
			"EnemyId": individual_id,
			"RoleType": 1,  # Regular enemy
			"Flags": adapted_enemy.get("Flags", 0) & 8,  # Inherit only the parent's wait state.

			"AppearanceNum": 1,
			"MaxAppearanceNum": 1,
			"GroupId": adapted_enemy["GroupId"],

			"AppearanceRule": {
				"Type": 2,  # External
				"Params": []
			},
			"Child": None,
			"SummonRule": None,

			"VisualId": "",
			"SurviveId": "",
			"PatrolPoints": [],
			"PriorityPoint": "",
			"ScenarioNo": adapted_enemy["ScenarioNo"]
		}

		external_enemies.append(external_enemy)

	return external_enemies


def adapt_episode_enemies_for_episode_layout(master_data, platoon_master_data):
	enemies = []

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
			"Params": [entry["_appearanceParam1"], str(entry["_appearanceIntParam1"])]
		}

		# EpisodeEnemyChild
		layout_entry["Child"] = {
			"Ids": entry["_childEnemyData"]["EnemyIds"],
			"Formation": "",
			"FormationPadding": [0, 0]
		}

		formation_id = entry["_childEnemyData"]["FormationId"]

		if formation_id != "":
			platoon = platoon_master_data[formation_id]

			print("Applied Formation", platoon["_id"], "to", entry["_id"])
			layout_entry["Child"]["Formation"] = platoon["Formation"]
			layout_entry["Child"]["FormationPadding"] = SerVec2toVec2(platoon["FormationPadding"])


		# EpisodeEnemySummonRule
		summon_data = entry["_summonEnemyData"]

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

		# "External" enemies that are spawned by parent/generator enemies
		if layout_entry["RoleType"] > 1:
			external_enemies = generate_external_enemies(layout_entry)
			enemies.extend(external_enemies)

	return enemies
