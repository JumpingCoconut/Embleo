
from .indexed import put_clip, indexed_data


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

    clips = {}
    for clip in track["clips"]:
        # print(clip)
        clip_MonoBehaviour = clip["behaviour"]
        clip_m_Name = clip["behaviour"]["m_Name"]

        if clip_m_Name in UPDATE_CLIPS:
            source, member = {
                'UpdateAttackInfo Clip': ('attackBaseInfo', 'attackBaseInfo'),
                'SpecialSkillMagic Clip': ('clipSettings', 'clip_SpecialSkillMagic'),
                'EnemyReceiveDamage Clip': ('setting', 'clip_EnemyReceiveDamage'),
            }[clip_m_Name]
            settings = clip_MonoBehaviour[source]
            index = settings.get('ClipIndex', clip_MonoBehaviour.get('clipIndex', len(clips)))
            put_clip(clips, index, {member: settings})

        elif clip_m_Name not in UPDATE_CLIPS_SKIP:
            print(owner_id, sequence_name, "-", clip_m_Name, "-", "Unknown update clip")

    UpdateParameterSetting['clipDatas'] = indexed_data(clips)
    UpdateParameterSetting['totalClipCount'] = len(UpdateParameterSetting['clipDatas'])
    return UpdateParameterSetting
