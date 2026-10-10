"""Explicit event-loop ownership of the opt-in raid transport prototype.

The HTTP server does not automatically instantiate this runtime. Its control
bridge may be shared with authenticated HTTP threads in the same process.
"""

import asyncio

from prizm_control import RoomControl
from prizm_listener import Listener
from prizm_rooms import Rooms
from prizm_room_service import RoomService
from prizm_sessions import SessionRegistry


class Runtime:
    def __init__(self, capacity, guild_provider=None, event_catalog=None,
                 eligibility_provider=None, room_settings_provider=None,
                 room_view_provider=None, player_provider=None, connection_provider=None,
                 battle_provider=None,
                 battle_character_provider=None,
                 battle_enemy_provider=None,
                 battle_minion_provider=None,
                 completion_provider=None,
                 **listener_limits):
        self.loop = asyncio.get_running_loop()
        self.registry = SessionRegistry(reconnect=True)
        self.rooms = Rooms(capacity)
        if battle_enemy_provider is None and battle_provider is not None:
            battle_enemy_provider = getattr(battle_provider, 'enemy_spawns', None)
        self.service = RoomService(self.rooms,self.registry,guild_provider,
                                   event_catalog,eligibility_provider,room_settings_provider,
                                   room_view_provider,player_provider,connection_provider,battle_provider,
                                   battle_character_provider,battle_enemy_provider,battle_minion_provider,
                                   completion_provider)
        self.listener = Listener(self.registry,self.service,**listener_limits)
        self.control = None
        self.closed = False
        self.lifecycle = asyncio.Lock()

    def _owner(self):
        if asyncio.get_running_loop() is not self.loop:
            raise RuntimeError('Runtime lifecycle belongs to its listener loop.')

    async def start(self, host, port, tls):
        self._owner()
        async with self.lifecycle:
            if self.closed or self.control is not None:
                raise RuntimeError('Runtime cannot be restarted.')
            sockets = await self.listener.start(host,port,tls)
            self.control = RoomControl(self.service)
            return sockets

    async def stop(self):
        self._owner()
        async with self.lifecycle:
            await self._stop()

    async def _stop(self):
        if self.closed:
            return
        self.closed = True
        if self.control is not None:
            self.control.close()
        try:
            await self.listener.stop()
        finally:
            # Admissions may never have opened sockets. Revoke those too.
            with self.rooms.lock:
                for account,room_id in list(self.rooms.memberships.items()):
                    self.registry.revoke(account,room_id)
                self.rooms.memberships.clear()
                self.rooms.rooms.clear()
