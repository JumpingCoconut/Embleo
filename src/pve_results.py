"""Atomic account-scoped completion journal with explicit settlement policy."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from accounts import AccountStore
from pve_completion import completion_request,completion_response

JOURNAL = 'PveCompletions.json'


class NativeCompletionRenderer:
    """Project current scoped saves; the policy supplies reward/ranking contents.

    Reward projection is explicit because presents, tickets and other collections
    may need adapters. Never substitute global defaults for account state.
    """
    def __init__(self, reward_projection):
        if not callable(reward_projection):
            raise ValueError('Account-scoped reward projection required.')
        self.reward_projection = reward_projection

    def __call__(self, saves, artifact, retire):
        reward = self.reward_projection(saves)
        object_fields = ('User','UserParameter','HcBalance')
        array_fields = ('UserPresents','UserItems','UserEquipments','UserTickets',
                        'UserStampBadge','UserCharacters','UserEventSkits','UserPanelMissions')
        if (type(reward) is not dict or set(reward) != set(object_fields+array_fields)
                or any(type(reward[name]) is not dict for name in object_fields)
                or any(type(reward[name]) is not list for name in array_fields)):
            raise ValueError('Complete native account reward projection required.')
        result = dict(Parameter=deepcopy(reward['UserParameter']),
                      Characters=deepcopy(reward['UserCharacters']),Reward=deepcopy(reward))
        if retire:
            return {'Result':result}
        if not {'RankingScore','Rewards','SpecialDrops'} <= set(artifact):
            raise ValueError('Explicit settlement ranking and reward records required.')
        return completion_response(dict(Result=result,RewardResult=deepcopy(reward),
            RankingScore=deepcopy(artifact['RankingScore']),Rewards=deepcopy(artifact['Rewards']),
            SpecialDrops=deepcopy(artifact['SpecialDrops'])),False)


class CompletionSaves:
    """Settlement callbacks cannot choose another account or commit early."""
    def __init__(self, store, account, writable):
        self._store,self._account,self._writable = store,account,writable

    def read(self, name):
        return self._store.read(self._account,name)

    def write(self, name, value):
        if not self._writable or name == JOURNAL:
            raise ValueError('Completion rendering and journal writes are restricted.')
        self._store.write(self._account,name,value)


class DurableCompletionProvider:
    """settle(saves, room, request, retire) validates claims and updates saves.

    It returns a compact JSON result artifact. render(readonly_saves, artifact,
    retire) builds the native response using current account state. The journal
    retains artifacts, never full inventory snapshots or submitted playlogs.
    Room/token checks belong to RoomService; policy owns gameplay validation.
    """
    def __init__(self, database, settle, render):
        if not callable(settle) or not callable(render):
            raise ValueError('Explicit settlement and result rendering required.')
        self.database = Path(database).resolve()
        self.settle,self.render = settle,render

    def __call__(self, account, room, data, retire):
        return self._complete(account,room,data,retire,False)

    def replay(self, account, room, data, retire):
        """Render an existing settlement; missing records never settle again."""
        return self._complete(account,room,data,retire,True)

    def _complete(self, account, room, data, retire, replay_only):
        request = completion_request(account,data,retire)
        prepared = room.get('PreparedBattle',{}).get(account)
        if prepared is None or prepared['EpisodeToken'] != request['EpisodeToken']:
            raise ValueError('Prepared account completion required.')
        battle = prepared.get('BattleId')
        if type(battle) is not str or not battle or len(battle) > 512:
            raise ValueError('Prepared battle identity required.')
        if not self.database.is_file():
            raise ValueError('Existing account database required.')
        fingerprint = hashlib.sha256(json.dumps([retire,request],sort_keys=True,
            separators=(',',':'),ensure_ascii=False).encode('utf-8')).hexdigest()
        store = AccountStore(self.database)
        try:
            if not store.connection.execute('SELECT 1 FROM accounts WHERE id=?',
                                            (account,)).fetchone():
                raise ValueError('Unknown completion account.')
            journal = (store.read(account,JOURNAL) if store.exists(account,JOURNAL)
                       else {'Version':1,'Battles':{}})
            if (type(journal) is not dict or type(journal.get('Version')) is not int
                    or journal['Version'] != 1
                    or type(journal.get('Battles')) is not dict):
                raise ValueError('Unsupported completion journal.')
            previous = journal['Battles'].get(battle)
            if previous is not None:
                if previous['RequestHash'] != fingerprint or previous['Retire'] is not retire:
                    raise ValueError('Conflicting durable battle completion.')
                artifact = deepcopy(previous['Artifact'])
            else:
                if replay_only:
                    raise ValueError('Durable completion record is missing.')
                artifact = self.settle(CompletionSaves(store,account,True),
                    deepcopy(room),deepcopy(request),retire)
                if type(artifact) is not dict:
                    raise ValueError('Compact completion artifact required.')
                encoded = json.dumps(artifact,allow_nan=False,ensure_ascii=False)
                if len(encoded.encode('utf-8')) > 64*1024:
                    raise ValueError('Completion artifact exceeds compact record limit.')
                artifact = json.loads(encoded)
            response = completion_response(self.render(CompletionSaves(store,account,False),
                deepcopy(artifact),retire),retire)
            json.dumps(response,allow_nan=False)
            if previous is None:
                journal['Battles'][battle] = dict(RequestHash=fingerprint,Retire=retire,Artifact=artifact)
                store.write(account,JOURNAL,journal)
            store.connection.commit()
            return deepcopy(response)
        except Exception:
            store.connection.rollback()
            raise
        finally:
            store.close()
