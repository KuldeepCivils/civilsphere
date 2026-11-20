"""Anonymous visitor and time-on-site counter.

A 'visitor' is one browser (random cookie), not a verified person. No names, IP addresses or user agents are stored.
A 'visit' starts when the site is opened in a new browser session (session cookie gone, e.g. after the browser was closed) or after
10+ minutes without activity; moving between pages, or leaving a tab open while active, stays one visit. Time only grows through client pings sent while the tab is visible
and the user was active in the last minute; each ping adds at most the real elapsed time (capped), so it cannot be inflated.
"""
import re
import secrets
import time
from datetime import datetime

SESSION_GAP = 600
MAX_PING = 20
_VID = re.compile(r"^[0-9a-f]{32}$")


def _now():
    return int(time.time())


def fmt_duration(sec):
    sec = int(sec or 0)
    if sec < 60:
        return f"{sec} sec"
    m = sec // 60
    if m < 60:
        return f"{m} min"
    return f"{m // 60} h {m % 60} min"


def touch(conn, vid, has_session=True):
    """Record a page view. Returns (visitor_id, is_new_cookie)."""
    now = _now()
    fresh = not (vid and _VID.match(vid))
    if fresh:
        vid = secrets.token_hex(16)
    if not conn.execute("SELECT 1 FROM visitors WHERE id=?", (vid,)).fetchone():
        conn.execute("INSERT INTO visitors(id,first_seen,last_seen) VALUES(?,?,?)", (vid, now, now))
    v = conn.execute("SELECT id,last_seen FROM visits WHERE visitor_id=? ORDER BY id DESC LIMIT 1", (vid,)).fetchone()
    if v and has_session and now - v["last_seen"] <= SESSION_GAP:
        conn.execute("UPDATE visits SET last_seen=?, pageviews=pageviews+1 WHERE id=?", (now, v["id"]))
    else:
        conn.execute("INSERT INTO visits(visitor_id,started_at,last_seen,pageviews) VALUES(?,?,?,1)", (vid, now, now))
        conn.execute("UPDATE visitors SET visits=visits+1 WHERE id=?", (vid,))
    conn.execute("UPDATE visitors SET last_seen=?, pageviews=pageviews+1 WHERE id=?", (now, vid))
    return vid, fresh


def ping(conn, vid):
    """Add active time to the current visit. Returns True if time was recorded."""
    if not (vid and _VID.match(vid)):
        return False
    now = _now()
    v = conn.execute("SELECT id,last_seen FROM visits WHERE visitor_id=? ORDER BY id DESC LIMIT 1", (vid,)).fetchone()
    if not v or now - v["last_seen"] > SESSION_GAP:
        return False
    delta = max(0, min(now - v["last_seen"], MAX_PING))
    conn.execute("UPDATE visits SET seconds=seconds+?, last_seen=? WHERE id=?", (delta, now, v["id"]))
    conn.execute("UPDATE visitors SET seconds=seconds+?, last_seen=? WHERE id=?", (delta, now, vid))
    return True


def stats(conn, vid=None):
    t = conn.execute("SELECT COUNT(*) n, COALESCE(SUM(visits),0) v, COALESCE(SUM(pageviews),0) p, COALESCE(SUM(seconds),0) s, MIN(first_seen) f FROM visitors").fetchone()
    mine = None
    if vid:
        mine = conn.execute("SELECT seconds FROM visits WHERE visitor_id=? ORDER BY id DESC LIMIT 1", (vid,)).fetchone()
    return {"visitors": t["n"], "visits": t["v"], "pageviews": t["p"], "time": fmt_duration(t["s"]), "seconds": t["s"],
            "since": datetime.fromtimestamp(t["f"]).strftime("%d %b %Y") if t["f"] else "-",
            "this_visit": fmt_duration(mine["seconds"] if mine else 0)}
