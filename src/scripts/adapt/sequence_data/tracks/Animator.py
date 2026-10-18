
def adapt_animator_track(track):
    base_attack_info = {}

    # print("Animator Track for", owner_id, action_name)

    clip_count = len(track["clips"])
    if clip_count > 1:
        pass
        # print(owner_id, action_name, "has Animator Track with {} clips".format(clip_count))

    for clip in track["clips"]:
        if clip["behaviour"].get("isAttack"):
            base_attack_info = clip["behaviour"]["attackBaseInfo"]
            pass

    return base_attack_info
