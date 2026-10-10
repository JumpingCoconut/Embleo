"""Persistent social systems using the authenticated request's transaction.

Prizm transport is a separate prerequisite for playable co-op battles. Never
return fabricated connection credentials or acknowledge unvalidated rewards.
"""

import datetime
import json
import secrets
import time

from flask import g, request

from accounts import AccountError
from profiles import utc_date


MULTIPLAYER_SCHEMA = """
CREATE TABLE direct_messages (
    seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL,
    sender TEXT NOT NULL REFERENCES accounts(id),
    recipient TEXT NOT NULL REFERENCES accounts(id),
    type INTEGER NOT NULL CHECK(type IN (1,2)), body TEXT NOT NULL,
    posted REAL NOT NULL, CHECK(sender != recipient)
);
CREATE INDEX direct_messages_pair ON direct_messages(sender,recipient,seq);
CREATE INDEX direct_messages_recipient ON direct_messages(recipient,sender,seq);
CREATE INDEX direct_messages_rate ON direct_messages(sender,posted);
CREATE TABLE message_destinations (
    owner TEXT NOT NULL REFERENCES accounts(id),
    target TEXT NOT NULL REFERENCES accounts(id), read_seq INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(owner,target), CHECK(owner != target)
);
CREATE TABLE direct_message_likes (
    message TEXT NOT NULL REFERENCES direct_messages(id) ON DELETE CASCADE,
    account TEXT NOT NULL REFERENCES accounts(id), PRIMARY KEY(message,account)
);
CREATE TABLE guilds (
    id TEXT PRIMARY KEY, code TEXT UNIQUE NOT NULL,
    leader TEXT NOT NULL REFERENCES accounts(id),
    settings TEXT NOT NULL, created REAL NOT NULL
);
CREATE INDEX guilds_created ON guilds(created);
CREATE TABLE guild_members (
    account TEXT PRIMARY KEY REFERENCES accounts(id),
    guild TEXT NOT NULL REFERENCES guilds(id) ON DELETE CASCADE,
    officer INTEGER NOT NULL DEFAULT 0, joined REAL NOT NULL,
    read_seq INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX guild_members_guild ON guild_members(guild,joined,account);
CREATE TABLE guild_applications (
    account TEXT PRIMARY KEY REFERENCES accounts(id),
    guild TEXT NOT NULL REFERENCES guilds(id) ON DELETE CASCADE,
    requested REAL NOT NULL
);
CREATE INDEX guild_applications_guild ON guild_applications(guild,requested,account);
CREATE TABLE guild_blocks (
    guild TEXT NOT NULL REFERENCES guilds(id) ON DELETE CASCADE,
    account TEXT NOT NULL REFERENCES accounts(id), PRIMARY KEY(guild,account)
);
CREATE TABLE guild_messages (
    seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL,
    guild TEXT NOT NULL REFERENCES guilds(id) ON DELETE CASCADE,
    sender TEXT NOT NULL REFERENCES accounts(id), body TEXT NOT NULL,
    cdata TEXT NOT NULL, posted REAL NOT NULL
);
CREATE INDEX guild_messages_guild ON guild_messages(guild,seq);
CREATE INDEX guild_messages_rate ON guild_messages(sender,posted);
CREATE INDEX guild_messages_posted ON guild_messages(posted);
CREATE TABLE guild_message_likes (
    message TEXT NOT NULL REFERENCES guild_messages(id) ON DELETE CASCADE,
    account TEXT NOT NULL REFERENCES accounts(id), PRIMARY KEY(message,account)
);
"""


def text(value, name, maximum=140, empty=False):
    if (not isinstance(value, str) or len(value) > maximum
            or (not empty and not value.strip()) or "\x00" in value):
        raise AccountError("Invalid " + name + ".")
    return value


def integer(value, name, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise AccountError("Invalid " + name + ".")
    return value


def boolean(value, name):
    if type(value) is not bool:
        raise AccountError("Invalid " + name + ".")
    return value


def identifiers(value, name, maximum=32):
    if not isinstance(value, list) or not 1 <= len(value) <= maximum:
        raise AccountError("Invalid " + name + ".")
    return list(dict.fromkeys(text(item, name, 64) for item in value))


def date_cursor(value):
    if value in (None, ""):
        return None
    text(value, "date", 64)
    try:
        parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError()
        return parsed.timestamp()
    except (ValueError, OverflowError) as error:
        raise AccountError("Invalid date.") from error


def posted_time(db):
    # The client formats guild cursors with four fractional digits. Match that
    # precision and advance across equal/backward clock readings so polling and
    # paging cannot skip or repeat messages solely through rounding.
    latest = db.execute("""SELECT MAX(value) FROM (
        SELECT MAX(posted) AS value FROM guild_messages UNION ALL
        SELECT MAX(created) AS value FROM guilds)""").fetchone()[0]
    ticks = int(time.time() * 10000)
    if latest is not None:
        ticks = max(ticks,round(latest * 10000) + 1)
    return ticks / 10000


class SocialStore:
    def __init__(self, store, account):
        self.store = store
        self.db = store.connection
        self.account = account

    def target(self, value, allow_self=False):
        target = self.store.find_account(text(value, "player identifier", 64))
        if target is None or (target == self.account and not allow_self):
            raise AccountError("Unknown player or invalid self target.")
        return target

    def blocked(self, target):
        return self.db.execute("""SELECT 1 FROM blocks
            WHERE (blocker_id=? AND blocked_id=?) OR (blocker_id=? AND blocked_id=?)""",
            (self.account, target, target, self.account)).fetchone() is not None

    def message_target(self, value):
        target = self.target(value)
        if self.blocked(target):
            raise AccountError("Messaging is blocked between these players.")
        return target

    def destination(self, target):
        self.db.execute("INSERT OR IGNORE INTO message_destinations(owner,target) VALUES (?,?)",
                        (self.account, target))

    def message_user(self, account):
        user = self.store.read(account, "User.json")
        param = self.store.read(account, "UserParameter.json")
        return {"UserId": account, "Name": user["name"],
                "CharacterId": param.get("FavoriteChrId", "pl001"),
                "EmblemId": param.get("EmblemId", "")}

    def direct_rows(self, target):
        return self.db.execute("""SELECT seq,id,sender,type,body,posted
            FROM direct_messages WHERE (sender=? AND recipient=?)
            OR (sender=? AND recipient=?) ORDER BY seq DESC LIMIT 100""",
            (self.account, target, target, self.account)).fetchall()[::-1]

    def direct_view(self, row):
        seq, mid, sender, kind, body, posted = row
        count, liked = self.db.execute("""SELECT COUNT(*),
            COALESCE(MAX(account=?),0) FROM direct_message_likes WHERE message=?""",
            (self.account, mid)).fetchone()
        return {"UserId": sender, "MessageId": mid, "Type": kind,
                "Message": body, "IsLike": bool(liked), "LikeCount": count,
                "PostedAt": utc_date(posted)}

    def direct_state(self, target):
        if self.blocked(target) or target == self.account:
            return "", False
        row = self.db.execute("""SELECT body FROM direct_messages
            WHERE (sender=? AND recipient=?) OR (sender=? AND recipient=?)
            ORDER BY seq DESC LIMIT 1""", (self.account,target,target,self.account)).fetchone()
        unread = self.db.execute("""SELECT 1 FROM direct_messages
            WHERE sender=? AND recipient=? AND seq > COALESCE(
                (SELECT read_seq FROM message_destinations WHERE owner=? AND target=?),0)
            LIMIT 1""", (target,self.account,self.account,target)).fetchone()
        return row[0] if row else "", bool(unread)

    def direct_unread(self):
        return bool(self.db.execute("""SELECT 1 FROM direct_messages m
            WHERE m.recipient=? AND m.seq > COALESCE((SELECT read_seq FROM
                message_destinations d WHERE d.owner=? AND d.target=m.sender),0)
            AND NOT EXISTS(SELECT 1 FROM blocks WHERE
                (blocker_id=? AND blocked_id=m.sender) OR (blocked_id=? AND blocker_id=m.sender))
            LIMIT 1""",(self.account,self.account,self.account,self.account)).fetchone())

    def check_post_rate(self):
        cutoff = time.time() - 60
        count = self.db.execute("""SELECT SUM(value) FROM (
            SELECT COUNT(*) AS value FROM direct_messages WHERE sender=? AND posted>?
            UNION ALL SELECT COUNT(*) AS value FROM guild_messages WHERE sender=? AND posted>?)""",
            (self.account,cutoff,self.account,cutoff)).fetchone()[0]
        if count >= 30:
            raise AccountError("Message limit reached. Try again in a minute.")

    def post_direct(self, target, data):
        kind = integer(data.get("Type"), "message type", 1, 2)
        body = text(data.get("Message"), "message", 140)
        self.check_post_rate()
        mid = secrets.token_hex(16)
        self.db.execute("""INSERT INTO direct_messages(id,sender,recipient,type,body,posted)
            VALUES (?,?,?,?,?,?)""", (mid,self.account,target,kind,body,time.time()))
        self.destination(target)
        self.db.execute("INSERT OR IGNORE INTO message_destinations(owner,target) VALUES (?,?)",
                        (target,self.account))
        return {"Messages": [self.direct_view(row) for row in self.direct_rows(target)]}

    def membership(self, account=None):
        return self.db.execute("SELECT guild,officer,joined FROM guild_members WHERE account=?",
                               (account or self.account,)).fetchone()

    def guild_id(self, value):
        row = self.db.execute("SELECT id FROM guilds WHERE id=? OR code=?",
                              (text(value, "guild identifier", 64), value)).fetchone()
        if not row:
            raise AccountError("Unknown guild.")
        return row[0]

    def guild_record(self, gid):
        row = self.db.execute("SELECT leader,settings,created,code FROM guilds WHERE id=?",
                              (gid,)).fetchone()
        if not row:
            raise AccountError("Unknown guild.")
        return row

    def require_member(self, gid=None, officer=False, leader=False):
        member = self.membership()
        if not member or (gid is not None and member[0] != gid):
            raise AccountError("Guild membership required.")
        gid = member[0]
        president = self.guild_record(gid)[0] == self.account
        if (leader and not president) or (officer and not (president or member[1])):
            raise AccountError("Insufficient guild permissions.")
        return gid

    def member_ids(self, gid):
        return [row[0] for row in self.db.execute(
            "SELECT account FROM guild_members WHERE guild=? ORDER BY joined,account", (gid,))]

    def guild_name(self, account):
        row = self.db.execute("""SELECT settings FROM guilds JOIN guild_members
            ON guilds.id=guild_members.guild WHERE account=?""", (account,)).fetchone()
        return json.loads(row[0])["Name"] if row else ""

    def user_guild(self, gid=None, exstatus=0):
        member = self.membership()
        if member and (gid is None or member[0] == gid):
            return {"Status": 1, "JoinedAt": utc_date(member[2]), "Exstatus": exstatus}
        application = self.db.execute("SELECT guild FROM guild_applications WHERE account=?",
                                      (self.account,)).fetchone()
        return {"Status": 2 if application and (gid is None or application[0] == gid) else 0,
                "JoinedAt": utc_date(0), "Exstatus": exstatus}

    def guild_view(self, gid):
        leader, settings, created, code = self.guild_record(gid)
        members = self.member_ids(gid)
        officers = [row[0] for row in self.db.execute(
            "SELECT account FROM guild_members WHERE guild=? AND officer=1 ORDER BY account", (gid,))]
        count, last = self.db.execute("SELECT COUNT(*),MAX(posted) FROM guild_messages WHERE guild=?",
                                      (gid,)).fetchone()
        return {"GuildId": gid, "ShortGuildId": code, "Status": 0,
                **json.loads(settings), "LastAccessAt": utc_date(last or created),
                "Members": [leader] + [a for a in members if a != leader],
                # Client role checks use Officers[0] for the leader and the
                # remaining entries for submasters.
                "Officers": [leader] + [a for a in officers if a != leader],
                "Level": 1, "Exp": 0, "Coin": 0,
                "CommentCount": min(count,32767), "BlockCount": self.db.execute(
                    "SELECT COUNT(*) FROM guild_blocks WHERE guild=?", (gid,)).fetchone()[0],
                "MemberCount": len(members), "LeaderName": self.message_user(leader)["Name"],
                "EventScore": 0}

    def applications(self, gid, user_view):
        member = self.membership()
        if not member or member[0] != gid or not (
                member[1] or self.guild_record(gid)[0] == self.account):
            return []
        results = []
        for account, posted in self.db.execute(
                "SELECT account,requested FROM guild_applications WHERE guild=? ORDER BY requested,account", (gid,)):
            view = user_view(account)
            results.append({"UserId": account, "Name": view["Name"],
                            "LastLoginAt": view["LastLoginAt"],
                            "UserCharacter": view["UserCharacter"], "RequestedAt": utc_date(posted)})
        return results

    def guild_top(self, user_view):
        member = self.membership()
        application = self.db.execute("SELECT guild FROM guild_applications WHERE account=?",
                                      (self.account,)).fetchone()
        gid = member[0] if member else application[0] if application else None
        return {"UserGuild": self.user_guild(), "Guild": self.guild_view(gid) if gid else None,
                "Members": [user_view(a) for a in self.member_ids(gid)] if gid else [],
                "Applications": self.applications(gid,user_view) if gid else []}

    def settings(self, data, previous=None):
        result = dict(previous or {})
        strings = {"Name": ("Name",32), "Desc": ("Description",140),
                   "Icon": ("Icon",128), "Title": ("Title",32),
                   "NotifyBody": ("NotificationBody",140)}
        defaults = {"Name": "", "Desc": "", "Icon": "emblem_em001_001",
                    "Title": "", "NotifyBody": ""}
        for key, (field, limit) in strings.items():
            if key in data or previous is None:
                result[field] = text(data.get(key,defaults[key]), key, limit, empty=key != "Name")
        for key, field, maximum, default in (
                ("Recruitment","Recruitment",2,1), ("Mood","Mood",5,0),
                ("Cadence","Cadence",1,0), ("MinPower","MinimumPower",2**31-1,0)):
            if key in data or previous is None:
                result[field] = integer(data.get(key,default), key, 0, maximum)
        # Combat power is not currently computed by profile handlers. Do not
        # promise power-gated membership until its authoritative calculation exists.
        if result["MinimumPower"] > 0:
            raise AccountError("Power-gated guild recruitment is not implemented.")
        return result

    def create_guild(self, data):
        if self.membership() or self.db.execute(
                "SELECT 1 FROM guild_applications WHERE account=?", (self.account,)).fetchone():
            raise AccountError("Already a guild member or applicant.")
        settings = self.settings(data)
        gid, code, now = secrets.token_hex(16), secrets.token_hex(4), posted_time(self.db)
        self.db.execute("INSERT INTO guilds VALUES (?,?,?,?,?)",
                        (gid,code,self.account,json.dumps(settings,ensure_ascii=False),now))
        self.db.execute("INSERT INTO guild_members(account,guild,joined) VALUES (?,?,?)",
                        (self.account,gid,now))
        return {"Guild": self.guild_view(gid)}

    def join(self, data, user_view):
        gid = self.guild_id(data.get("GuildId"))
        cancel = boolean(data.get("IsCancel",False), "cancel flag")
        if cancel:
            self.db.execute("DELETE FROM guild_applications WHERE account=? AND guild=?", (self.account,gid))
        else:
            if self.membership():
                raise AccountError("Already a guild member.")
            pending = self.db.execute("SELECT guild FROM guild_applications WHERE account=?", (self.account,)).fetchone()
            if pending and pending[0] != gid:
                raise AccountError("Cancel the existing application first.")
            settings = json.loads(self.guild_record(gid)[1])
            if settings["Recruitment"] == 0 or self.db.execute(
                    "SELECT 1 FROM guild_blocks WHERE guild=? AND account=?", (gid,self.account)).fetchone():
                raise AccountError("Guild is not accepting this player.")
            if len(self.member_ids(gid)) >= 24:
                raise AccountError("Guild is full.")
            if settings["Recruitment"] == 2:
                self.add_member(gid,self.account)
            else:
                self.db.execute("INSERT OR IGNORE INTO guild_applications VALUES (?,?,?)",
                                (self.account,gid,time.time()))
        return {"UserGuild": self.user_guild(gid,1 if cancel else 0),
                "Guild": self.guild_view(gid), "Members": [user_view(a) for a in self.member_ids(gid)]}

    def add_member(self, gid, account):
        if self.membership(account) or len(self.member_ids(gid)) >= 24:
            raise AccountError("Player already joined a guild or guild is full.")
        if self.db.execute("SELECT 1 FROM guild_blocks WHERE guild=? AND account=?", (gid,account)).fetchone():
            raise AccountError("Player is blocked by the guild.")
        self.db.execute("INSERT INTO guild_members(account,guild,joined) VALUES (?,?,?)", (account,gid,time.time()))
        self.db.execute("DELETE FROM guild_applications WHERE account=?", (account,))

    def guild_rows(self, gid, cursor=None, newer=False, count=50):
        clause = ""
        params = [gid,self.account,self.account]
        if cursor is not None:
            clause = " AND posted " + (">" if newer else "<") + " ?"
            params.append(cursor)
        params.append(count)
        order = "ASC" if newer else "DESC"
        rows = self.db.execute("""SELECT seq,id,sender,body,cdata,posted FROM guild_messages
            WHERE guild=? AND NOT EXISTS(SELECT 1 FROM blocks
                WHERE (blocker_id=? AND blocked_id=sender)
                   OR (blocked_id=? AND blocker_id=sender))""" + clause +
            " ORDER BY seq " + order + " LIMIT ?",params).fetchall()
        return rows if newer else rows[::-1]

    def guild_message_view(self, row):
        seq,mid,sender,body,cdata,posted = row
        count,liked = self.db.execute("""SELECT COUNT(*),COALESCE(MAX(account=?),0)
            FROM guild_message_likes WHERE message=?""",(self.account,mid)).fetchone()
        return {"GuildMessageId": mid, "Type": 1, "UserId": sender,
                "IsGuest": False, "Message": body, "Cdata": cdata,
                "PostedAt": utc_date(posted), "History": 0, "PhData": [], "Info": [],
                "Like": count, "IsLiked": bool(liked)}

    def guild_messages(self, gid, rows, user_view):
        if rows:
            self.db.execute("UPDATE guild_members SET read_seq=MAX(read_seq,?) WHERE account=? AND guild=?",
                            (max(row[0] for row in rows),self.account,gid))
        return {"Messages": [self.guild_message_view(row) for row in rows],
                "Posters": [user_view(a) for a in dict.fromkeys(row[2] for row in rows)],
                "Guild": self.guild_view(gid), "UserGuild": self.user_guild(gid)}

    def guild_unread(self):
        return bool(self.db.execute("""SELECT 1 FROM guild_messages m JOIN guild_members u
            ON m.guild=u.guild WHERE u.account=? AND m.seq>u.read_seq AND m.sender!=?
            AND NOT EXISTS(SELECT 1 FROM blocks WHERE
                (blocker_id=? AND blocked_id=m.sender) OR (blocked_id=? AND blocker_id=m.sender))
            LIMIT 1""", (self.account,self.account,self.account,self.account)).fetchone())


def register_multiplayer(app, request_object, pack, user_view, error_response):
    raw_request_object = request_object

    def normalize_fields(fields):
        # The client serializes request fields in camelCase. Accept PascalCase
        # too for tools, rejecting conflicting aliases rather than choosing one.
        result = {}
        for key,value in fields.items():
            if not isinstance(key,str) or not key:
                raise AccountError("Invalid request field.")
            normalized = key[0].upper() + key[1:]
            if normalized in result and (result[normalized] != value
                    or type(result[normalized]) is not type(value)):
                raise AccountError("Conflicting request fields.")
            result[normalized] = value
        return result

    def request_object():
        return normalize_fields(raw_request_object())

    def social():
        return SocialStore(g.account_store,g.account_id)

    def payload():
        # Existing read APIs accept GET as well as MessagePack POST.
        return normalize_fields(dict(request.args)) if request.method == "GET" else request_object()

    @app.route("/api/message/top", methods=["GET","POST"])
    def message_top():
        store = social()
        friends = g.account_store.relationship_lists(g.account_id)["FollowUsers"]
        destinations = [r[0] for r in store.db.execute(
            "SELECT target FROM message_destinations WHERE owner=? ORDER BY target",(g.account_id,))]
        return pack({"FriendUsers": [user_view(a) for a in friends if not store.blocked(a)],
                     "DestUsers": [user_view(a) for a in destinations if not store.blocked(a)]})

    @app.route("/api/message/list", methods=["GET","POST"])
    def message_list():
        store = social()
        target = store.message_target(payload().get("TargetUserId"))
        rows = store.direct_rows(target)
        store.destination(target)
        if rows:
            store.db.execute("UPDATE message_destinations SET read_seq=MAX(read_seq,?) WHERE owner=? AND target=?",
                             (rows[-1][0],g.account_id,target))
        return pack({"User": store.message_user(g.account_id), "TargetUser": store.message_user(target),
                     "Messages": [store.direct_view(row) for row in rows]})

    @app.route("/api/message/post", methods=["POST"])
    def message_post():
        store,data = social(),request_object()
        return pack(store.post_direct(store.message_target(data.get("TargetUserId")),data))

    @app.route("/api/message/register-dest", methods=["POST"])
    @app.route("/api/message/remove-dest", methods=["POST"])
    def message_destination():
        store,data = social(),request_object()
        target = store.target(data.get("DestUserId"))
        if request.path.endswith("register-dest"):
            if store.blocked(target):
                raise AccountError("Messaging is blocked between these players.")
            store.destination(target)
        else:
            store.db.execute("DELETE FROM message_destinations WHERE owner=? AND target=?",(g.account_id,target))
        return pack({})

    @app.route("/api/message/like", methods=["POST"])
    def message_like():
        store,data = social(),request_object()
        target = store.message_target(data.get("TargetUserId"))
        mid = text(data.get("MessageId"),"message identifier",64)
        like = boolean(data.get("Like"),"like flag")
        row = store.db.execute("""SELECT seq,id,sender,type,body,posted FROM direct_messages
            WHERE id=? AND ((sender=? AND recipient=?) OR (sender=? AND recipient=?))""",
            (mid,g.account_id,target,target,g.account_id)).fetchone()
        if not row:
            raise AccountError("Unknown conversation message.")
        if like:
            store.db.execute("INSERT OR IGNORE INTO direct_message_likes VALUES (?,?)",(mid,g.account_id))
        else:
            store.db.execute("DELETE FROM direct_message_likes WHERE message=? AND account=?",(mid,g.account_id))
        return pack({"Message": store.direct_view(row)})

    @app.route("/api/guild/top", methods=["GET","POST"])
    def persistent_guild_top():
        return pack(social().guild_top(user_view))

    @app.route("/api/guild/create", methods=["POST"])
    def guild_create():
        return pack(social().create_guild(request_object()))

    @app.route("/api/guild/update", methods=["POST"])
    def guild_update():
        store,data = social(),request_object()
        gid = store.require_member(officer=True)
        settings = store.settings(data,json.loads(store.guild_record(gid)[1]))
        store.db.execute("UPDATE guilds SET settings=? WHERE id=?",(json.dumps(settings,ensure_ascii=False),gid))
        return pack({"Guild": store.guild_view(gid)})

    @app.route("/api/guild/info", methods=["GET","POST"])
    def guild_info():
        store = social()
        gid = store.guild_id(payload().get("GuildId"))
        return pack({"Guild": store.guild_view(gid), "Members": [user_view(a) for a in store.member_ids(gid)]})

    @app.route("/api/guild/search", methods=["POST"])
    def guild_search():
        store,data = social(),request_object()
        name = text(data.get("Name",""),"guild name",64,empty=True).casefold()
        count = integer(data.get("Count",50),"count",1,100)
        cursor = date_cursor(data.get("StartDate"))
        filters = {field: integer(data.get(key,-1),key,-1,maximum)
                   for key,field,maximum in (("Recruitment","Recruitment",2),("Mood","Mood",5),
                       ("Cadence","Cadence",1),("MinPower","MinimumPower",2**31-1))}
        guilds = []
        for gid,code,settings,created in store.db.execute("""SELECT g.id,g.code,g.settings,
                COALESCE((SELECT MAX(posted) FROM guild_messages WHERE guild=g.id),g.created) AS accessed
                FROM guilds g ORDER BY accessed DESC,g.id"""):
            settings = json.loads(settings)
            if cursor is not None and created >= cursor:
                continue
            if name and name not in settings["Name"].casefold() and name not in (gid,code):
                continue
            if any(value != -1 and settings[field] != value for field,value in filters.items()):
                continue
            guilds.append(store.guild_view(gid))
            if len(guilds) == count:
                break
        return pack({"Guilds": guilds})

    @app.route("/api/guild/join-apply", methods=["POST"])
    def guild_join_apply():
        return pack(social().join(request_object(),user_view))

    @app.route("/api/guild/join-approve", methods=["POST"])
    def guild_join_approve():
        store,data = social(),request_object()
        gid = store.require_member(officer=True)
        targets = [store.target(a) for a in identifiers(data.get("TargetUserId"),"players",24)]
        accept = boolean(data.get("IsAccept"),"accept flag")
        for account in targets:
            if not store.db.execute("SELECT 1 FROM guild_applications WHERE account=? AND guild=?",(account,gid)).fetchone():
                raise AccountError("Unknown guild application.")
            if accept:
                store.add_member(gid,account)
            else:
                store.db.execute("DELETE FROM guild_applications WHERE account=? AND guild=?",(account,gid))
        return pack({"TargetUserId": targets, "ErrorUserId": [], "Errors": [], "IsAccept": accept,
                     "Guild": store.guild_view(gid), "Members": [user_view(a) for a in store.member_ids(gid)],
                     "Applications": store.applications(gid,user_view)})

    @app.route("/api/guild/leave", methods=["POST"])
    def guild_leave():
        store = social()
        gid = store.require_member()
        if store.guild_record(gid)[0] == g.account_id:
            raise AccountError("Transfer leadership or disband before leaving.")
        store.db.execute("DELETE FROM guild_members WHERE account=?",(g.account_id,))
        return pack({"UserGuild": store.user_guild(exstatus=2)})

    @app.route("/api/guild/promote", methods=["POST"])
    @app.route("/api/guild/devolution", methods=["POST"])
    def guild_role():
        store,data = social(),request_object()
        gid = store.require_member(leader=True)
        target = store.target(data.get("TargetUserId"))
        member = store.membership(target)
        if not member or member[0] != gid:
            raise AccountError("Player is not a guild member.")
        if request.path.endswith("promote"):
            promote = boolean(data.get("IsPromote"),"promotion flag")
            store.db.execute("UPDATE guild_members SET officer=? WHERE account=?",(int(promote),target))
        else:
            store.db.execute("UPDATE guilds SET leader=? WHERE id=?",(target,gid))
            store.db.execute("UPDATE guild_members SET officer=0 WHERE account=?",(target,))
        return pack({"Guild": store.guild_view(gid)})

    @app.route("/api/guild/drop-member", methods=["POST"])
    def guild_drop_member():
        store,data = social(),request_object()
        gid = store.require_member(officer=True)
        leader = store.guild_record(gid)[0]
        targets = [store.target(a) for a in identifiers(data.get("TargetUserId"),"players",24)]
        block = boolean(data.get("IsBlock",False),"block flag")
        for account in targets:
            member = store.membership(account)
            if not member or member[0] != gid or account == leader or (member[1] and g.account_id != leader):
                raise AccountError("Cannot remove this guild member.")
            store.db.execute("DELETE FROM guild_members WHERE account=?",(account,))
            if block:
                store.db.execute("INSERT OR IGNORE INTO guild_blocks VALUES (?,?)",(gid,account))
        return pack({"TargetUserId": targets, "Guild": store.guild_view(gid)})

    @app.route("/api/guild/disband", methods=["POST"])
    def guild_disband():
        store,data = social(),request_object()
        gid = store.guild_id(data.get("GuildId"))
        store.require_member(gid,leader=True)
        guild = store.guild_view(gid)
        members = [user_view(a) for a in store.member_ids(gid)]
        store.db.execute("DELETE FROM guilds WHERE id=?",(gid,))
        guild.update(Status=1,Members=[],Officers=[],MemberCount=0)
        return pack({"Guild": guild, "Members": members})

    @app.route("/api/guild/block-list", methods=["GET","POST"])
    def guild_block_list():
        store = social()
        gid = store.require_member(officer=True)
        return pack({"Users": [user_view(row[0]) for row in store.db.execute(
            "SELECT account FROM guild_blocks WHERE guild=? ORDER BY account",(gid,))]})

    @app.route("/api/guild/block", methods=["POST"])
    def guild_block():
        store,data = social(),request_object()
        gid = store.require_member(officer=True)
        target = store.target(data.get("TargetUserId"))
        block = boolean(data.get("IsBlock"),"block flag")
        member = store.membership(target)
        if member and member[0] == gid:
            raise AccountError("Remove the member before blocking them.")
        if block:
            store.db.execute("INSERT OR IGNORE INTO guild_blocks VALUES (?,?)",(gid,target))
            store.db.execute("DELETE FROM guild_applications WHERE guild=? AND account=?",(gid,target))
        else:
            store.db.execute("DELETE FROM guild_blocks WHERE guild=? AND account=?",(gid,target))
        return pack({"TargetUserId": target, "IsBlock": block})

    @app.route("/api/guild/message", methods=["POST"])
    @app.route("/api/guild/post-message", methods=["POST"])
    def guild_message():
        store,data = social(),request_object()
        supplied_gid = data.get("GuildId")
        gid = store.guild_id(supplied_gid) if supplied_gid else store.require_member()
        store.require_member(gid)
        posting = request.path.endswith("post-message")
        if posting:
            body = text(data.get("Message"),"message",140)
            cdata = text(data.get("Cdata") if data.get("Cdata") is not None else "",
                         "message data",1024,empty=True)
            cursor = date_cursor(data.get("LastDate"))
            store.check_post_rate()
            store.db.execute("""INSERT INTO guild_messages(id,guild,sender,body,cdata,posted)
                VALUES (?,?,?,?,?,?)""",(secrets.token_hex(16),gid,g.account_id,body,cdata,posted_time(store.db)))
            rows = store.guild_rows(gid,cursor,newer=cursor is not None)
        else:
            cursor = date_cursor(data.get("StartDate"))
            newer = boolean(data.get("IsNewer",False),"direction flag")
            count = integer(data.get("Count",50),"count",1,100)
            rows = store.guild_rows(gid,cursor,newer,count)
        return pack(store.guild_messages(gid,rows,user_view))

    @app.route("/api/guild/like-message", methods=["POST"])
    @app.route("/api/guild/delete-message", methods=["POST"])
    def guild_message_action():
        store,data = social(),request_object()
        gid = store.guild_id(data.get("GuildId"))
        store.require_member(gid)
        mids = identifiers(data.get("MessageId"),"message identifiers")
        deleting = request.path.endswith("delete-message")
        remove = False if deleting else boolean(data.get("IsRemove"),"remove flag")
        member = store.membership()
        moderator = bool(member[1]) or store.guild_record(gid)[0] == g.account_id
        rows = []
        for mid in mids:
            row = store.db.execute("SELECT seq,id,sender,body,cdata,posted FROM guild_messages WHERE id=? AND guild=?",(mid,gid)).fetchone()
            if not row or store.blocked(row[2]):
                raise AccountError("Unknown guild message.")
            if deleting:
                if row[2] != g.account_id and not moderator:
                    raise AccountError("Cannot delete another member's message.")
                store.db.execute("DELETE FROM guild_messages WHERE id=?",(mid,))
            elif remove:
                store.db.execute("DELETE FROM guild_message_likes WHERE message=? AND account=?",(mid,g.account_id))
            else:
                store.db.execute("INSERT OR IGNORE INTO guild_message_likes VALUES (?,?)",(mid,g.account_id))
            rows.append(row)
        return pack({"MessageId": mids, "Guild": store.guild_view(gid)} if deleting else
                    {"Messages": [store.guild_message_view(row) for row in rows]})

    # The API is only the control plane. Prizm supplies authenticated TCP/UDP
    # relay/RPC services for lobby membership and synchronized battle state.
    @app.route("/api/pve/<action>", methods=["GET","POST"])
    def pve_unavailable(action):
        if action == 'list' and app.config.get('PVE_PUBLICATION') is not None:
            if request.method == 'GET' and any(len(values) != 1 for _,values in request.args.lists()):
                return error_response('Ambiguous event selection.',400)
            data = payload()
            if set(data) != {'EventId'} or type(data['EventId']) is not str:
                return error_response('Invalid event selection.',400)
            try:
                return pack({'PveEvent':app.config['PVE_PUBLICATION'].selected(g.account_id,data['EventId'])})
            except ValueError:
                return error_response('Event is not available.',400)
        if action in ("room-list","room-info","create","join","matching","start","end","retire","heart-beat") and app.config.get("PVE_HTTP") is not None:
            if action in ("create","join","matching","start","end","retire","heart-beat") and request.method != "POST":
                return error_response("Room admission requires POST.",405)
            try:
                adapter = app.config["PVE_HTTP"]
                handler = {"room-list":adapter.room_list,"room-info":adapter.room_info,
                           "create":adapter.create,"join":adapter.join,
                           "matching":adapter.matching,"start":adapter.start,
                           "end":adapter.end,"retire":adapter.retire,"heart-beat":adapter.heart_beat}[action]
                if request.method == 'GET' and any(len(values) != 1 for _,values in request.args.lists()):
                    return error_response('Ambiguous room discovery.',400)
                data = payload()
                if request.method == 'GET' and 'Difficulty' in data:
                    value = data['Difficulty']
                    if not value.isascii() or not value.isdecimal() or len(value) > 10:
                        return error_response('Invalid difficulty.',400)
                    data['Difficulty'] = int(value)
                # Authentication only read this transaction. Every adapter
                # submission waits on the same listener loop; an overlapping
                # completion may need its own account write transaction there.
                # Release this lock before any listener-bound handler waits.
                g.account_store.connection.rollback()
                return pack(handler(g.account_id,data))
            except ValueError:
                return error_response("Invalid or unavailable room discovery.",400)
            except (RuntimeError, TimeoutError):
                return error_response("Room discovery temporarily unavailable.",503)
        if action in ("room-list","get-recently-matching"):
            return pack({"Rooms": []} if action == "room-list" else {"Users": []})
        if action not in ("list","create","join","start","end","retire","matching","modify",
                          "heart-beat","room-info","ranking","reward-list","character-ranking",
                          "character-ranking-result","character-ranking-reward-list","select-ranking-character"):
            return error_response("Unknown co-op route.",404)
        return error_response("Co-op raids require the unimplemented Prizm transport and event data.",501)

    @app.route('/api/event/list', methods=['GET','POST'])
    def configured_event_list():
        publication = app.config.get('PVE_PUBLICATION')
        return pack({'Events':publication.event_list() if publication is not None else []})

    # Flask's catch-all otherwise returns static success fixtures on GET to a
    # mutation. Register an explicit 405 handler for every social mutation.
    mutations = ("message/post","message/like","message/register-dest","message/remove-dest",
                 "guild/create","guild/update","guild/search","guild/join-apply","guild/join-approve",
                 "guild/leave","guild/promote","guild/devolution","guild/drop-member","guild/disband",
                 "guild/block","guild/message","guild/post-message","guild/like-message","guild/delete-message")
    for index,path in enumerate(mutations):
        app.add_url_rule("/api/" + path,"social_method_" + str(index),
                         lambda: error_response("This social endpoint requires POST.",405),methods=["GET"])
