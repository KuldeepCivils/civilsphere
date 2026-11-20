"""Daily brief generation: deterministic, source-grounded, versioned. No AI text is produced here.
Every line is either a source headline/extract (with link) or a stored syllabus mapping."""
import json
import re
from datetime import datetime, timezone, timedelta
from jinja2 import Environment, FileSystemLoader, select_autoescape
from . import config
from .icons import icon
from .ingest import now_iso

_env = Environment(loader=FileSystemLoader(str(config.BASE_DIR / "templates")), autoescape=select_autoescape(["html"]))
_env.globals["icon"] = icon
from .richtext import rich as _rich_filter
_env.filters["rich"] = _rich_filter
GENERATOR = "rule-based-v1 (no AI)"


def pipeline_warnings(conn):
    w = []
    if not conn.execute("SELECT 1 FROM sources WHERE active=1").fetchone():
        w.append("No sources are active. This brief only reflects manually imported or earlier data.")
    failed = conn.execute(
        "SELECT COUNT(*) FROM fetch_jobs WHERE status='failed' AND started_at>=?",
        ((datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ"),)).fetchone()[0]
    if failed:
        w.append(f"{failed} fetch job(s) failed in the last 24 hours; coverage may be incomplete.")
    if conn.execute("SELECT 1 FROM news_events WHERE data_origin!='live' LIMIT 1").fetchone():
        w.append("Some events are not live data (demo/manual); they are labelled in the brief.")
    return w


def sentence_points(text, n=6):
    """Split the publisher's own extract into short bullet sentences (no rewriting)."""
    if not text:
        return []
    parts = [x.strip() for x in re.split(r"(?<=[.!?])\s+", " ".join(text.split())) if len(x.strip()) > 3]
    return parts[:n]


def sec_kind(heading):
    """Colour class for a study-note section, from its heading."""
    h = (heading or "").lower()
    for key, kind in (("key data", "dat"), ("data point", "dat"), ("numbers", "dat"), ("statistic", "dat"), ("concept tag", "tag"), ("keyword", "tag"),
                      ("recent", "rec"), ("latest", "rec"), ("way forward", "fwd"), ("challenge", "chal"), ("concern", "chal"), ("issue", "chal"), ("significance", "sig"), ("implication", "sig"),
                      ("histor", "hist"), ("academic", "hist"), ("evolution", "evo"), ("precedent", "evo"), ("timeline", "evo"), ("provision", "prov"),
                      ("feature", "prov"), ("background", "bg"), ("about", "bg"), ("concept", "con"), ("term", "con")):
        if key in h:
            return kind
    return "oth"


def card_extras(conn, event_id, extract):
    row = conn.execute("SELECT * FROM ai_notes WHERE event_id=?", (event_id,)).fetchone()
    ai = None
    if row:
        ai = {"model": row["model"], "at": row["generated_at"], "points": json.loads(row["key_points"]),
              "linkage": json.loads(row["static_linkage"]), "theme": row["mains_theme"],
              "overview": json.loads(row["overview"]) if row["overview"] else [], "summary": row["summary"] or "", "background": row["background"] or "",
              "perspective": json.loads(row["perspective"]) if row["perspective"] else [],
              "about": json.loads(row["about"]) if row["about"] else [],
              "table": json.loads(row["info_table"]) if row["info_table"] else None,
              "facts": json.loads(row["facts"]) if row["facts"] else [],
              "sections": [dict(s, kind=sec_kind(s["heading"])) for s in (json.loads(row["sections"]) if row["sections"] else [])],
              "prelims": json.loads(row["prelims"]) if row["prelims"] else []}
    from . import enrich, pyq
    return {"points": sentence_points(extract), "ai": ai, "ctx": enrich.load_context(conn, event_id), "pyq": pyq.for_event(conn, event_id)}


def _pick_image(srcs):
    """First publisher-supplied image among the event's sources, with credit. Hotlinked, never downloaded or stored."""
    for x in srcs:
        if x["image_url"]:
            return {"url": x["image_url"], "credit": x["publisher"]}
    return None


def brief_meaning(text, limit=220):
    """Short 'meaning' = the publisher's own feed text, trimmed at a word boundary. Not AI."""
    if not text:
        return None
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "\u2026"


def collect_events(conn, date=None, paper="", min_score=0.0, q="", limit=200, since=None, show_all=False):
    """Group events: paper -> syllabus topic -> rows. Unmapped events go to a 'needs review' group."""
    sql = """SELECT e.id, e.headline, e.event_date, e.relevance_score, e.needs_review, e.data_origin,
                    p.code paper, p.name paper_name, t.name topic, t.official_wording official, m.confidence, m.matched_terms, p.sort_order psort, t.sort_order tsort
             FROM news_events e LEFT JOIN event_topic_mappings m ON m.event_id=e.id AND m.is_primary=1
             LEFT JOIN syllabus_topics t ON t.id=m.topic_id LEFT JOIN syllabus_papers p ON p.id=t.paper_id
             WHERE e.merged_into IS NULL AND e.status!='rejected' AND e.relevance_score>=?"""
    if not show_all:  # default view: only stories that map to a syllabus topic and are not sport/market/entertainment noise
        sql += " AND e.noise=0 AND m.topic_id IS NOT NULL"
    args = [min_score]
    if date:
        sql += " AND e.event_date=?"; args.append(date)
    if since:
        sql += " AND e.event_date>=?"; args.append(since)
    if paper:
        sql += " AND p.code=?"; args.append(paper)
    if q:
        sql += " AND e.headline LIKE ? ESCAPE '\\'"
        args.append("%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
    sql += " ORDER BY COALESCE(p.sort_order, 99), COALESCE(t.sort_order, 99), e.relevance_score DESC LIMIT ?"
    args.append(limit)
    rows = conn.execute(sql, args).fetchall()
    sections, no = {}, 0
    for r in rows:
        srcs = conn.execute(
            """SELECT si.title, si.url, si.published_at, si.snippet, si.image_url, s.name publisher
               FROM source_items si JOIN sources s ON s.id=si.source_id WHERE si.event_id=?""", (r["id"],)).fetchall()
        no += 1
        extract = next((x["snippet"] for x in srcs if x["snippet"]), None)
        key = (r["paper"] or "NA", r["paper_name"] or "Unmapped (needs review)")
        sections.setdefault(key, {}).setdefault(r["topic"] or "No syllabus topic matched", []).append(
            {"no": no, "event": r, "sources": srcs, "meaning": brief_meaning(extract), "image": _pick_image(srcs), **card_extras(conn, r["id"], extract),
             "publishers": sorted({x["publisher"] for x in srcs})})
    return sections, len(rows)


def collect_for_topic(conn, topic_id, limit=100):
    """All events mapped (primary or secondary) to one syllabus topic, newest first, in table-ready form."""
    t = conn.execute("SELECT t.name topic, p.code paper, p.name paper_name FROM syllabus_topics t JOIN syllabus_papers p ON p.id=t.paper_id WHERE t.id=?", (topic_id,)).fetchone()
    rows = conn.execute(
        """SELECT e.id, e.headline, e.event_date, e.relevance_score, e.needs_review, e.data_origin,
                  m.confidence, m.matched_terms, m.is_primary, t2.official_wording official, t2.name topic
           FROM event_topic_mappings m JOIN news_events e ON e.id=m.event_id JOIN syllabus_topics t2 ON t2.id=m.topic_id
           WHERE m.topic_id=? AND e.merged_into IS NULL AND e.status!='rejected'
           ORDER BY e.event_date DESC, e.relevance_score DESC LIMIT ?""", (topic_id, limit)).fetchall()
    items = []
    for i, r in enumerate(rows, 1):
        srcs = conn.execute(
            """SELECT si.title, si.url, si.published_at, si.snippet, si.image_url, s.name publisher
               FROM source_items si JOIN sources s ON s.id=si.source_id WHERE si.event_id=?""", (r["id"],)).fetchall()
        extract = next((x["snippet"] for x in srcs if x["snippet"]), None)
        items.append({"no": i, "event": r, "sources": srcs, "meaning": brief_meaning(extract), "image": _pick_image(srcs), **card_extras(conn, r["id"], extract),
                      "publishers": sorted({x["publisher"] for x in srcs})})
    return ({(t["paper"], t["paper_name"]): {t["topic"]: items}} if items else {}), len(items)


def collect(conn, date, min_score=0.0):
    return collect_events(conn, date=date, min_score=min_score)


def generate_daily(conn, date, min_score=0.0):
    """Returns (ok, message, report_id). Refuses to create an empty brief."""
    sections, n = collect(conn, date, min_score)
    if n == 0:
        return False, f"No mapped events found for {date}; nothing was generated.", None
    warnings = pipeline_warnings(conn)
    gen_at = now_iso()
    pretty = datetime.strptime(date, "%Y-%m-%d").strftime("%d %B %Y").lstrip("0")
    body = _env.get_template("brief_body.html").render(
        date=date, date_pretty=pretty, sections=sections, n=n, warnings=warnings, generated_at=gen_at, generator=GENERATOR)
    r = conn.execute("SELECT id FROM reports WHERE kind='daily' AND period_start=?", (date,)).fetchone()
    if r:
        rid = r["id"]
    else:
        rid = conn.execute("INSERT INTO reports(kind,period_start,period_end) VALUES('daily',?,?)", (date, date)).lastrowid
    ver = (conn.execute("SELECT MAX(version) FROM report_versions WHERE report_id=?", (rid,)).fetchone()[0] or 0) + 1
    conn.execute(
        """INSERT INTO report_versions(report_id,version,status,body_html,generator,input_event_count,warnings,generated_at)
           VALUES(?,?, 'generated', ?,?,?,?,?)""", (rid, ver, body, GENERATOR, n, "\n".join(warnings), gen_at))
    return True, f"Brief for {date} saved as version {ver} ({n} events).", rid


def event_card(conn, event_id):
    """Single-event section structure for the event detail page (same shape as collect_events)."""
    row = conn.execute(
        """SELECT e.id, e.headline, e.event_date, e.relevance_score, e.needs_review, e.data_origin,
                  p.code paper, p.name paper_name, t.name topic, t.official_wording official, m.confidence, m.matched_terms
           FROM news_events e LEFT JOIN event_topic_mappings m ON m.event_id=e.id AND m.is_primary=1
           LEFT JOIN syllabus_topics t ON t.id=m.topic_id LEFT JOIN syllabus_papers p ON p.id=t.paper_id WHERE e.id=?""", (event_id,)).fetchone()
    srcs = conn.execute(
        """SELECT si.title, si.url, si.published_at, si.snippet, si.image_url, s.name publisher
           FROM source_items si JOIN sources s ON s.id=si.source_id WHERE si.event_id=?""", (event_id,)).fetchall()
    extract = next((x["snippet"] for x in srcs if x["snippet"]), None)
    item = {"no": 1, "event": row, "sources": srcs, "meaning": brief_meaning(extract), "image": _pick_image(srcs),
            **card_extras(conn, event_id, extract), "publishers": sorted({x["publisher"] for x in srcs})}
    return {(row["paper"] or "NA", row["paper_name"] or "Unmapped (needs review)"): {row["topic"] or "No syllabus topic matched": [item]}}
