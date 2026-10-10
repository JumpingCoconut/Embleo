"""Read raid admission profiles from detached account combat snapshots."""

from prizm_lobby import player_payload


class SnapshotRaidPlayers:
    """selection resolves character/platform/version/rank from server state.

    SnapshotCombatStats must include User.json and any selection documents.
    The callback receives that same account preparation, never a Flask DB
    handle or client-supplied combat values.
    """
    def __init__(self, snapshots, presentation, selection):
        if not callable(selection):
            raise ValueError('Server-owned raid selection resolver required.')
        self.snapshots = snapshots
        self.presentation = presentation
        self.selection = selection

    def read(self, account, character_id=None):
        prepared = self.snapshots.prepare(account)
        selected = self.selection(account, prepared)
        if (type(selected) is not dict
                or set(selected) != {'CharacterId','Platform','ClientVersion','MissionRank'}
                or selected['Platform'] not in ('android','ios')):
            raise ValueError('Invalid resolved raid selection.')
        character_id = selected['CharacterId'] if character_id is None else character_id
        paired = prepared.battle_character(account,character_id,
                                           self.presentation.character(character_id))
        totals = prepared.character(account,character_id)
        user = prepared.save(account,'User.json')
        if type(user) is not dict or user.get('id') != account:
            raise ValueError('Raid profile belongs to another account.')
        character = paired['CharacterData']
        player = dict(UserId=account,Name=user['name'],CharacterId=character_id,
            CharacterLevel=character[4],CharacterPower=totals['Power'],
            VisualEquipments=character[8],Order=0,IsHost=False,
            CliVersion=selected['ClientVersion'],Ready=0,CostumeSpells=character[9],
            WeaponSpells=character[10],CharacterHp=totals['Hp'],
            CharacterAttack=totals['Attack'],CharacterDefense=totals['Defense'],
            MissionRank=selected['MissionRank'])
        player_payload(player)
        return player, dict(Power=totals['Power'],Platform=selected['Platform'],
                            ClientVersion=selected['ClientVersion'])

    def player(self, account):
        return self.read(account)[0]

    __call__ = player

    def for_character(self, account, character_id):
        return self.read(account,character_id)[0]

    def admission(self, account):
        """Permit the native lobby to restore its local last selection."""
        player = self.player(account)
        player.update(CharacterId='',CharacterLevel=0,CharacterPower=0,
            VisualEquipments=[],CostumeSpells=[],WeaponSpells=[],
            CharacterHp=0,CharacterAttack=0,CharacterDefense=0,Ready=0)
        player_payload(player,allow_unselected=True)
        return player

    def admission_eligibility(self, account):
        """Room admission uses owned capacity, before client lobby selection."""
        prepared = self.snapshots.prepare(account)
        selected = self.selection(account,prepared)
        rows = prepared.save(account,'UserCharacter.json')
        if not rows:
            raise ValueError('Owned characters required for raid admission.')
        power = max(prepared.character(account,row['CharacterId'])['Power'] for row in rows)
        return dict(Power=power,Platform=selected['Platform'],ClientVersion=selected['ClientVersion'])

    def eligibility(self, account):
        return self.read(account)[1]
