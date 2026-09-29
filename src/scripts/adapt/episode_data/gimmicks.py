import os
import json

def SerVec3toVec3(SerializableVector3):
	vector_3 = [
		SerializableVector3["x"],
		SerializableVector3["y"],
		SerializableVector3["z"]
	]

	return vector_3

def load_json(path):
	with open(path, "r", encoding='utf-8') as f:
		return json.load(f)


def get_all_episode_scenario_gimmick_id_list(episode_id):
	episode_scenario_gimmicks_id_list = []

	scenario_file_path = "./data/masterdata/scenario/{0}.json".format(episode_id)
	if os.path.isfile(scenario_file_path):
		scenario_data = load_json(scenario_file_path)

		for entry in scenario_data:
			if entry["ProgressType"] == 5:
				for gimmick in entry["Progress"]["Gimmicks"]:
					episode_scenario_gimmicks_id_list.append(gimmick["GimmickId"])

	return episode_scenario_gimmicks_id_list


def get_episode_location_id_list(episode_id):
	location_id_list = []

	episode_master_data_path = "./data/extract/masterdata/EpisodeMasterDataObject.json"
	episode_master_data_object = load_json(episode_master_data_path)

	for entry in episode_master_data_object["Datas"]:
		if episode_id == entry["ID"]:
			location_id_list = entry["_locationIDs"]

	return location_id_list


def get_episode_area_id_list(episode_id):
	area_id_list = []

	episode_location_id_list = get_episode_location_id_list(episode_id)

	stage_location_data_path = "./data/extract/masterdata/StageLocationMasterDataObject.json"
	stage_location_data = load_json(stage_location_data_path)

	# Get all area ids
	for entry in stage_location_data["Datas"]:
		location_id = entry["_id"]

		if location_id in episode_location_id_list:

			for stage_map in entry["_stageMapInfos"]:

				# 0 means area, 2 is sky and horizon texture
				if stage_map["_situation"] == 0:
					area_id_list.append(stage_map["_id"])

	return area_id_list


# episode layout gimmicks
def adapt_episode_layout_gimmick(entry):
	gimmick = {
		"EpisodeGimmickId": entry["_id"],
		"ResourceId": entry["_masterID"],
		"ActionType": entry["_typeID"],
		"Status": [{
			"Status": entry["_startStatus"],
			"ScenarioNo": [entry["_startScenarioNo"], entry["_endScenarioNo"]]
		}],
		# "StartType": 1,

		# "StageMapID" : "SCH01_Area01",

		"Scale": SerVec3toVec3(entry["_modelScale"]),
		"ScenarioNo": [entry["_startScenarioNo"], entry["_endScenarioNo"]]
	}

	action_type = entry["_typeID"]
	params = json.loads(entry["_addParamJson"])

	# print(action_type)
	# print(params)

	# SetEvent, doesn't need filling in
	if action_type == 0:
		pass

	# Jump (from high places)
	elif action_type == 1:
		gimmick["Jump"] = {
			"WarpPointId": params["_warpPointID"]
		}

	# Unused?
	elif action_type == 2:
		return {}

	# CrawlSide (FixedDirectionMovement)
	# Crawling or moving along the wall 
	elif action_type == 3:
		gimmick["DirectionMove"] = {
			"WarpPointId": params["_warpPointID"]
		}

	# GimmickExecute
	# Does it need filling in?
	# Mana Wall in Hugo's Ep1
	# Somethig in Lisette's Ep2
	# Something in both Crossroads
	elif action_type == 4:
		pass

	# Mana Wall. Present in Celia's Ep1 and Bastien's Ep1
	# Doesn't need filling in
	elif action_type == 5:
		pass

	elif action_type == 6:
		# MoveLimit

		gimmick["MoveLimit"] = {
			"CollisionType": params["_collisionType"],
			"CollisionSize": SerVec3toVec3(params["_collisionSize"]),
			"MoveOutEvent": dict,
			"NpcLimitLength": params["_npcLimitLength"]
		}

		gimmick["MoveLimit"]["MoveOutEvent"] = {
			"Flag": 0,
			# "TriggerType": "MISSING VARIABLE TYPE",
			# "ActionType": "MISSING VARIABLE TYPE",
			"ScriptPath": params["_scriptID"],
			"Param": "",
			"Drop": {"Id": params["EventDropInfo"]["ID"]}
		}


	elif action_type == 7:
		gimmick["DominationBase"] = {
			"Ids": params["_gateIDs"],
			"GateReverses": params["_gateReverses"]
		}

	elif action_type == 8:
		gimmick["Gate"] = {
			"AutoClose": params["_autoClose"]
		}

	elif action_type == 9:
		gimmick["CollisionSet"] = {
			"Shape": params["_hitShape"],
			"Size": SerVec3toVec3(params["_hitSize"]),
			"Interaction": params["_interaction"]
		}

	# Automatic gate in Imperial Laboratory
	elif action_type == 10:
		gimmick["Gate"] = {
			"AutoClose": params["_autoClose"]
		}

	# Flamethrower
	elif action_type == 11:
		gimmick["Flamethrower"] = {
			"LoopTime": params["_loopTime"],
			"StopTime": params["_stopTime"],
			"Damage": params["_damage"],
			"DamageInterval": params["_damageInterval"]
		}

	# MineTrap, doesn't need special properties
	elif action_type == 12:
		pass

	# PlayerAction
	elif action_type == 13:
		gimmick["PlayerAction"] = {
			"WarpPointId": params["_warpPointID"],
			"ActionDirection": params["_actionDirection"]
		}

	# RolligStoneTrap, doesn't need special properties
	elif action_type == 14:
		pass

	# Arrow trap
	elif action_type == 15:
		gimmick["BowTrap"] = {
			"FireInterval": params["_fireInterval"],
			"Damage": params["_damage"],
			"SearchDistance": params["_searchDistance"],
			"SearchWidth": params["_searchWidth"],
			"SearchWidthFarOffset": params["_searchWidthFarOffset"],
			"MaxFireDistance": params["_maxFireDistance"],
		}

	# AttackSwitch (only in Michelle Ep.1) doesn't need special properties
	elif action_type == 16:
		pass

	# Pendulum Trap
	elif action_type == 17:
		gimmick["PendulumTrap"] = {
			"LoopTime": params["_loopTime"],
			"InitAngleRate": params["_initAngleRate"],
			"Damage": params["_damage"]
		}

	# Camera Shake, doesn't need special properties
	elif action_type == 18:
		pass

	# Warp portals from Charle's Ep 1
	elif action_type == 19:
		gimmick["WarpPortal"] = {
			"TargetWarpPointId": params["_targetWarpPointID"],
			"ExitEffectDisable": params["_exitEffectDisable"],
			"IsOneWay": params["_isOneWay"]
		}

	# Patara Hardle (twigs on the road), doesn't need special properties
	elif action_type == 20:
		pass

	# Celia's Shooting Cover, doesn't need special properties
	elif action_type == 21:
		pass

	# StageControl, responsible for loading sub-areas
	elif action_type == 22:
		gimmick["StageControl"] = {
			"StageMapId": [],
			"StageObjectName": [],
			"VisibleNonActive": params["_visibleNonActive"],
			"VisibleActive": params["_visibleActive"],
			"VisibleOption1": params["_visibleOption1"],
			"VisibleOption2": params["_visibleOption2"]
		}

		# Loads sub-areas
		for stage_object in params["_stageObjects"]:
			gimmick["StageControl"]["StageMapId"].append(stage_object["_stageMapID"])
			gimmick["StageControl"]["StageObjectName"].append(stage_object["_stageObjectName"])

			'''
			new_status = {
				"Status": entry["_startStatus"],
				"ScenarioNo": [entry["_startScenarioNo"], entry["_endScenarioNo"]]
			}

			gimmick["Status"].append(new_status)
			'''

	# Goal Line (from Secret Missions), doesn't need special properties
	elif action_type == 23:
		pass

	# Rope trap that has a forced introduction scene in Raoul's Ep.1
	elif action_type == 24:
		gimmick["RopeTrap"] = {
			"Damage": params["_damage"],
			"MazzleReverse": params["_mazzleReverse"]
		}

	# Pressure plate puzzle from Raoul Ep.1 and right at the end of Raoul Ep.2
	# Pressure plate puzzle switch. Doesn't need filling in
	elif action_type == 25:
		pass

	# Pressure plate puzzle reset switch
	elif action_type == 26:
		gimmick["ResetSwitch"] = {
			"TargetGimmickIds": params["_targetGimmickIDs"]
		}

	# Gate levers in Maxime's Ep 1
	elif action_type == 27:
		gimmick["KillEnemyExecute"] = {
			"TargetEnemyId": params["_targetEnemyID"]
		}

	else:
		return {}

	return gimmick


def adapt_gimmicks_for_episode_layout(debug_data, episode_id):
	gimmicks = []

	for entry in debug_data["Datas"]:
		gimmick = adapt_episode_layout_gimmick(entry)

		if gimmick != {}:
			gimmicks.append(gimmick)

	add_area_gimmicks = True

	# "Pre-packaged" gimmicks, that are implied to be present on a map
	if add_area_gimmicks:
		# Get all area IDs
		episode_area_id_list = get_episode_area_id_list(episode_id)

		# Get all area gimmicks
		stage_option_gimmick_data = load_json("./data/masterdata/StageOptionGimmickMasterData.json")

		# Go through all optional gimmicks and add only those,
		# which appear in used locations
		for area_entry in stage_option_gimmick_data["Datas"]:
			stage_map_id = area_entry["_id"]

			if stage_map_id in episode_area_id_list:

				for gimmick in area_entry["infos"]:
					adapted_gimmick = adapt_episode_layout_gimmick(gimmick)

					# Assign StageMapID, so the gimmick appears where it should.
					adapted_gimmick["StageMapID"] = stage_map_id

					# gimmick_id = gimmick["_id"]
					# print(adapted_gimmick["StageMapID"], gimmick_id)

					gimmicks.append(adapted_gimmick)

	return gimmicks
