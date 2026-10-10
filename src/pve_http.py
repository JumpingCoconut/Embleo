"""Authenticated PvE HTTP adapter; runtime and providers are explicitly wired."""

from concurrent.futures import TimeoutError


class PveHttp:
    def __init__(self, control, timeout=5):
        if type(timeout) not in (int,float) or timeout <= 0:
            raise ValueError('Invalid PvE HTTP timeout.')
        self.control = control
        self.timeout = timeout

    def room_list(self, account_id, data):
        if (type(account_id) is not str or not account_id
                or type(data) is not dict
                or set(data) != {'EventId','Difficulty','PveVersion'}
                or type(data['EventId']) is not str or not data['EventId']
                or type(data['PveVersion']) is not str or not data['PveVersion']
                or type(data['Difficulty']) is not int or not 0 <= data['Difficulty'] < 2**31):
            raise ValueError('Invalid room list request.')
        future = self.control.submit('discover_event',account_id,data['EventId'],
                                     data['Difficulty'],data['PveVersion'])
        return {'Rooms':self._read(future)}

    def room_info(self, account_id, data):
        if (type(account_id) is not str or not account_id or type(data) is not dict
                or set(data) != {'EventId','RoomId','PveVersion'}
                or any(type(value) is not str or not value for value in data.values())):
            raise ValueError('Invalid room information request.')
        future = self.control.submit('info_event',account_id,data['EventId'],
                                     data['RoomId'],data['PveVersion'])
        return {'Room':self._read(future)}

    def create(self, account_id, data):
        if (type(account_id) is not str or not account_id or type(data) is not dict
                or set(data) != {'EpisodeId','PublicLevel','PveVersion'}
                or type(data['EpisodeId']) is not str or not data['EpisodeId']
                or type(data['PveVersion']) is not str or not data['PveVersion']
                or type(data['PublicLevel']) is not int or data['PublicLevel'] not in (1,2,3)):
            raise ValueError('Invalid room creation request.')
        future = self.control.submit('create_http',account_id,data['EpisodeId'],
                                     data['PveVersion'],data['PublicLevel'])
        return self._write(future)

    def join(self, account_id, data):
        if (type(account_id) is not str or not account_id or type(data) is not dict
                or set(data) != {'RoomId','JoinRoute','PveVersion'}
                or type(data['RoomId']) is not str or not data['RoomId']
                or type(data['PveVersion']) is not str or not data['PveVersion']
                or type(data['JoinRoute']) is not int or data['JoinRoute'] not in (1,2,3)):
            raise ValueError('Invalid room join request.')
        return self._write(self.control.submit('join_http',account_id,data['RoomId'],
                                               data['PveVersion'],data['JoinRoute']))

    def matching(self, account_id, data):
        if (type(account_id) is not str or not account_id or type(data) is not dict
                or not {'EventId','Difficulty','PveVersion'} <= set(data)
                or set(data) - {'EventId','Difficulty','PveVersion','MaxPower'}
                or type(data['EventId']) is not str or not data['EventId']
                or type(data['PveVersion']) is not str or not data['PveVersion']
                or type(data['Difficulty']) is not int or not 0 <= data['Difficulty'] < 2**31
                or data.get('MaxPower') is not None and type(data['MaxPower']) is not str):
            raise ValueError('Invalid matching request.')
        return self._write(self.control.submit('matching_http',account_id,data['EventId'],
                                               data['Difficulty'],data['PveVersion']))

    def start(self, account_id, data):
        if type(data) is dict and type(data.get('MemberIds')) is list and len(data['MemberIds']) == 4:
            data = dict(data,MemberIds=list(data['MemberIds']))
            while data['MemberIds'] and data['MemberIds'][-1] is None:
                data['MemberIds'].pop()
        if (type(account_id) is not str or not account_id or type(data) is not dict
                or set(data) != {'EpisodeId','CharacterId','MemberIds','MemberCharacterIds'}
                or any(type(data[field]) is not str or not data[field]
                       for field in ('EpisodeId','CharacterId'))
                or any(type(data[field]) is not list or not 1 <= len(data[field]) <= 32
                       or any(type(value) is not str or not value for value in data[field])
                       for field in ('MemberIds','MemberCharacterIds'))
                or len(data['MemberIds']) != len(data['MemberCharacterIds'])
                or len(set(data['MemberIds'])) != len(data['MemberIds'])):
            raise ValueError('Invalid battle start request.')
        return self._read(self.control.submit('start_http',account_id,data['EpisodeId'],
            data['CharacterId'],data['MemberIds'],data['MemberCharacterIds']))

    def _write(self, future):
        try:
            return future.result(self.timeout)
        except TimeoutError:
            if future.cancel():
                raise
            # Running listener operations are synchronous and must be bounded
            # by their server providers. Collect their actual result instead of
            # abandoning a mutation that may have admitted a player.
            return future.result()

    def end(self, account_id, data):
        from pve_completion import completion_request
        request = completion_request(account_id,data)
        return self._write(self.control.submit('complete_http',account_id,request,False))

    def heart_beat(self, account_id, data):
        if (type(account_id) is not str or not account_id or type(data) is not dict
                or set(data) != {'RoomId'} or type(data['RoomId']) is not str
                or not data['RoomId'] or len(data['RoomId']) > 512):
            raise ValueError('Invalid raid heartbeat request.')
        return self._read(self.control.submit('heartbeat_http',account_id,data['RoomId']))

    def retire(self, account_id, data):
        from pve_completion import completion_request
        request = completion_request(account_id,data,True)
        return self._write(self.control.submit('complete_http',account_id,request,True))

    def _read(self, future):
        try:
            return future.result(self.timeout)
        except TimeoutError:
            # Read-only operation: an already-running lookup has no admission
            # side effects. A queued lookup can be cancelled safely.
            future.cancel()
            raise
