
UPDATE_CLIPS = [
    "UpdateAttackInfo Clip",
    "SpecialSkillMagic Clip",
    "EnemyReceiveDamage Clip"
]

UPDATE_CLIPS_SKIP = [
    "LookAtTarget Clip",
    "UpdateDisableStageCamera Clip",
    "UpdateAimMarker Clip",
    "UpdateBlink Clip",
    "UpdateTargetList Clip",
    "RemoveCharacterPush Clip",
    "VFXEffectPause Clip",
    "CharacterEffectPause Clip",

    # Charles
    "UpdateMinionFade Clip",

    # Child Amelie
    "MotionSwitchCountSpeedUp Clip",
    "MotionSwitchCountUp Clip",
    "StartMotionSwitchCount Clip"
]


def adapt_update_parameter_track(track, sequence_name, owner_id):
    UpdateParameterSetting = {
        "id": owner_id,
        "sequenceName": sequence_name,
        "totalClipCount": 0,
        "clipCount": [],
        "clipDatas": []
    }

    # print(action["action_name"])

    for clip in track["clips"]:
        # print(clip)
        clip_MonoBehaviour = clip["behaviour"]
        clip_m_Name = clip["behaviour"]["m_Name"]

        if clip_m_Name in UPDATE_CLIPS:
            adapted_update_clip = {

            }

            UpdateParameterSetting["totalClipCount"] += 1

            adapted_update_clip["attackBaseInfo"] = clip_MonoBehaviour.get("attackBaseInfo")
            adapted_update_clip["clip_SpecialSkillMagic"] = clip_MonoBehaviour.get("clipSettings")
            adapted_update_clip["clip_EnemyReceiveDamage"] = clip_MonoBehaviour.get("setting")

            UpdateParameterSetting["clipDatas"].append(adapted_update_clip)

        elif clip_m_Name not in UPDATE_CLIPS_SKIP:
            print(owner_id, sequence_name, "-", clip_m_Name, "-", "Unknown update clip")

    return UpdateParameterSetting
