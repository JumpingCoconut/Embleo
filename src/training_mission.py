"""Checkpoint bootstrap for training layouts which have no scenario asset."""

import secrets
from itsdangerous import BadSignature, URLSafeSerializer


_tokens = URLSafeSerializer(secrets.token_bytes(32), salt='training-mission')


def mission_token(account_id, mission_id, character_id):
    return _tokens.dumps([account_id, mission_id, character_id])


def token_character(token, account_id, mission_id):
    try:
        values = _tokens.loads(token)
    except (BadSignature, TypeError, ValueError) as error:
        raise ValueError('Training mission token is unavailable.') from error
    if (type(values) is not list or len(values) != 3
            or values[:2] != [account_id, mission_id] or type(values[2]) is not str):
        raise ValueError('Training mission token does not match this account and stage.')
    return values[2]


def checkpoint_scenario(checkpoints):
    # Training assets contain the same checkpoint layout as secret missions,
    # but no EpisodeScenarioMasterDataObject. Use the existing secret-mission
    # checkpoint bootstrap, taking its identity/range from the installed layout.
    if len(checkpoints) != 1:
        raise ValueError('Training mission requires one initial checkpoint.')
    checkpoint = checkpoints[0]
    number = checkpoint['_startScenarioNo']
    identity = str(number).zfill(5)
    return [dict(Id=identity, ScenarioNo=number, ProgressType=1, Progress=dict(
        ProgressCheckPointId=identity, LayoutCheckPointId=checkpoint['_id'],
        RequestSave=True, IsReload=True,
        IsDarkenRestart=bool(checkpoint['IsDarkenRestart']), Progress=[]))]
