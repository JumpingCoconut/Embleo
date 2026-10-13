"""Persistent episode discussion using the authenticated account transaction."""

import secrets
import time

from flask import g, request
from accounts import AccountError
from multiplayer import SocialStore, boolean, text
from profiles import utc_date


COMMENT_SCHEMA = """
CREATE TABLE episode_comments (
    seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL,
    episode TEXT NOT NULL, author TEXT NOT NULL REFERENCES accounts(id),
    body TEXT NOT NULL, posted REAL NOT NULL
);
CREATE INDEX episode_comments_episode ON episode_comments(episode,seq);
CREATE INDEX episode_comments_author ON episode_comments(author,posted);
CREATE TABLE episode_comment_likes (
    comment TEXT NOT NULL REFERENCES episode_comments(id) ON DELETE CASCADE,
    account TEXT NOT NULL REFERENCES accounts(id), PRIMARY KEY(comment,account)
);
"""


def register_episode_comments(app, payload, pack, user_view, error_response):
    def view(row):
        _, identifier, episode, author, body, posted = row
        profile = user_view(author)
        count, liked = g.account_store.connection.execute("""SELECT COUNT(*),
            COALESCE(MAX(account=?),0) FROM episode_comment_likes WHERE comment=?""",
            (g.account_id,identifier)).fetchone()
        return dict(UserEpisodeCommentId=identifier, EpisodeId=episode,
            UserName=profile['Name'], CharacterId=profile['UserCharacter']['CharacterId'],
            IconUrl=profile['IconUrl'], EmblemId=profile['EmblemId'], Comment=body,
            IsLike=bool(liked), IsOwn=author == g.account_id, LikeCount=count,
            PostedAt=utc_date(posted))

    def find(identifier):
        row = g.account_store.connection.execute(
            'SELECT seq,id,episode,author,body,posted FROM episode_comments WHERE id=?',
            (text(identifier,'comment identifier',64),)).fetchone()
        if row is None or SocialStore(g.account_store,g.account_id).blocked(row[3]):
            raise AccountError('Unknown episode comment.')
        return row

    @app.route('/api/episode/comment-list', methods=['POST'])
    def comment_list():
        episode = text(payload().get('EpisodeId'),'episode identifier',128)
        rows = g.account_store.connection.execute("""SELECT seq,id,episode,author,body,posted
            FROM episode_comments c WHERE episode=? AND NOT EXISTS(SELECT 1 FROM blocks
            WHERE (blocker_id=? AND blocked_id=c.author)
               OR (blocked_id=? AND blocker_id=c.author)) ORDER BY seq DESC LIMIT 100""",
            (episode,g.account_id,g.account_id)).fetchall()
        return pack({'Comments':[view(row) for row in rows]})

    @app.route('/api/episode/comment', methods=['POST'])
    def comment_post():
        data = payload()
        episode = text(data.get('EpisodeId'),'episode identifier',128)
        body = text(data.get('Comment'),'comment',140)
        SocialStore(g.account_store,g.account_id).check_post_rate()
        identifier = secrets.token_hex(16)
        g.account_store.connection.execute("""INSERT INTO episode_comments
            (id,episode,author,body,posted) VALUES (?,?,?,?,?)""",
            (identifier,episode,g.account_id,body,time.time()))
        return pack({'Comment':view(find(identifier))})

    @app.route('/api/episode/like-comment', methods=['POST'])
    def comment_like():
        data = payload()
        row = find(data.get('EpisodeCommentId'))
        liked = boolean(data.get('Like'),'like flag')
        db = g.account_store.connection
        if liked:
            db.execute('INSERT OR IGNORE INTO episode_comment_likes VALUES (?,?)',
                       (row[1],g.account_id))
        else:
            db.execute('DELETE FROM episode_comment_likes WHERE comment=? AND account=?',
                       (row[1],g.account_id))
        return pack({'Comment':view(row)})

    @app.route('/api/episode/delete-comment', methods=['POST'])
    def comment_delete():
        row = find(payload().get('EpisodeCommentId'))
        if row[3] != g.account_id:
            raise AccountError('Only the author can delete this comment.')
        g.account_store.connection.execute('DELETE FROM episode_comments WHERE id=?',(row[1],))
        return pack({})

    for action in ('comment-list','comment','like-comment','delete-comment'):
        app.add_url_rule('/api/episode/' + action,'comment_method_' + action,
            lambda: error_response('This comment endpoint requires POST.',405),methods=['GET'])
