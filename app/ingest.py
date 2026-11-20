"""Ingestion pipeline: fetch -> validate -> normalise -> dedupe -> cluster -> map -> score.

Deterministic rules only (no AI). Stores metadata + short feed snippets, never full articles.
Retrieved text is treated as untrusted data: it is stripped of markup and only ever matched
against keyword lists; it is never executed or used as instructions.
"""
import functools
import hashlib
import html
import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

import requests

from . import config

MAX_FEED_BYTES = 5_000_000
SNIPPET_MAX = 600  # short factual extract only (copyright-conscious)
CLUSTER_WINDOW_DAYS = 3
CLUSTER_MIN_JACCARD = 0.5
CLUSTER_MIN_SHARED = 3
MAP_THRESHOLD = 0.30
REVIEW_BELOW = 0.50

DEFAULT_WEIGHTS = {"syllabus": 0.50, "reliability": 0.20, "corroboration": 0.20, "recency": 0.10}
RELIABILITY = {"official": 1.0, "high": 0.8, "medium": 0.6, "unrated": 0.4, "low": 0.2}

STOP = set("a an the of in on at to for and or with by from as is are was were be been it its this that "
           "after over into amid says say said new will may not no India's indias indian".lower().split())
TRACKING = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "ref", "gclid", "fbclid", "ocid"}


# ---------- helpers ----------
def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def strip_html(text):
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", text or "")
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def canonical_url(url):
    p = urlparse((url or "").strip())
    q = [(k, v) for k, v in parse_qsl(p.query) if k.lower() not in TRACKING]
    path = p.path.rstrip("/") or "/"
    return urlunparse((p.scheme.lower(), p.netloc.lower().removeprefix("www."), path, "", urlencode(q), ""))


def tokens(title):
    words = re.findall(r"[a-z0-9]+", (title or "").lower())
    return {w for w in words if w not in STOP and len(w) > 2}


def jaccard(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


def parse_date(s):
    if not s:
        return None
    try:
        d = parsedate_to_datetime(s)
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------- parsing ----------
def _text(el, *names):
    for n in names:
        for child in el:
            if child.tag.split("}")[-1] == n:
                txt = "".join(child.itertext()).strip()
                if txt:
                    return txt
    return None


def parse_feed(data: bytes):
    """Parse RSS 2.0 / Atom. Returns list of dicts. Raises ValueError on invalid feed."""
    if len(data) > MAX_FEED_BYTES:
        raise ValueError("Feed larger than size limit")
    data = data.lstrip(b"\xef\xbb\xbf \t\r\n")  # BOM / leading whitespace
    if re.match(rb"<!doctype\s+html|<html", data[:200], re.I):
        raise ValueError("The site returned a web page instead of a news feed (address wrong, or the site blocks automated readers)")
    if re.search(rb"<!DOCTYPE|<!ENTITY", data[:2000], re.I):
        raise ValueError("Feed with DOCTYPE/ENTITY declarations rejected (security)")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        raise ValueError(f"Not valid XML: {e}")
    out = []
    for el in root.iter():
        tag = el.tag.split("}")[-1]
        if tag not in ("item", "entry"):
            continue
        title = _text(el, "title")
        link = _text(el, "link")
        if not link:
            for child in el:
                if child.tag.split("}")[-1] == "link" and child.get("href"):
                    link = child.get("href")
                    break
        desc = _text(el, "description", "summary", "content")
        image = extract_image(el, "".join(c.text or "" for c in el if c.tag.split("}")[-1] in ("description", "summary", "content")))
        out.append({
            "title": strip_html(title or ""), "url": (link or "").strip(),
            "published": parse_date(_text(el, "pubDate", "published", "updated", "date")),
            "author": _text(el, "creator", "author"),
            "snippet": strip_html(desc or "")[:SNIPPET_MAX], "image": image,
        })
    if not out and root.tag.split("}")[-1] not in ("rss", "feed", "RDF"):
        raise ValueError("Document is XML but not an RSS/Atom feed")
    return out


IMG_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif")


def _clean_image(url):
    url = (url or "").strip()
    return url if url.startswith("https://") and len(url) < 1000 else None


def extract_image(el, raw_desc):
    """Publisher-supplied image only: media:thumbnail / media:content / image enclosure / first <img> in the item HTML."""
    for child in el.iter():
        name = child.tag.split("}")[-1]
        url = child.get("url")
        if name == "thumbnail" and url:
            return _clean_image(url)
        if name == "content" and url and (child.get("medium") == "image" or (child.get("type") or "").startswith("image/")
                                           or urlparse(url).path.lower().endswith(IMG_EXT)):
            return _clean_image(url)
        if name == "enclosure" and url and ((child.get("type") or "").startswith("image/") or urlparse(url).path.lower().endswith(IMG_EXT)):
            return _clean_image(url)
    for child in el:
        if child.tag.split("}")[-1] == "encoded" and child.text:
            raw_desc = (raw_desc or "") + child.text
    m = re.search(r"<img[^>]+src=[\"']([^\"']+)", raw_desc or "", re.I)
    return _clean_image(m.group(1)) if m else None


def validate_item(it):
    if not it["title"] or not it["url"]:
        return "missing title or url"
    if urlparse(it["url"]).scheme not in ("http", "https"):
        return "non-http url"
    return None


# ---------- fetching ----------
def http_get(url):
    r = requests.get(url, timeout=config.FETCH_TIMEOUT, headers={"User-Agent": config.USER_AGENT},
                     stream=True)
    r.raise_for_status()
    data = r.raw.read(MAX_FEED_BYTES + 1, decode_content=True)
    return data


def test_source(source):
    """Fetch+parse without storing. Returns (ok, message, count)."""
    if source["access_method"] != "rss" or not source["feed_url"]:
        return False, "Not an RSS source; no automated test available (connector not implemented).", 0
    try:
        items = parse_feed(http_get(source["feed_url"]))
    except Exception as e:  # noqa: BLE001 - report any failure to admin
        return False, f"{type(e).__name__}: {e}", 0
    return True, f"Feed parsed: {len(items)} entries.", len(items)


# ---------- storage / dedupe / cluster ----------
def store_items(conn, source_id, items, origin="live"):
    """Insert items. Returns (seen, new, rejected). Dedupes on canonical URL and, per source, content hash."""
    seen = new = rejected = 0
    retrieved = now_iso()
    for it in items:
        seen += 1
        if validate_item(it):
            rejected += 1
            continue
        canon = canonical_url(it["url"])
        chash = hashlib.sha256(" ".join(sorted(tokens(it["title"]))).encode()).hexdigest()
        existing = conn.execute("SELECT id, image_url FROM source_items WHERE canonical_url=?", (canon,)).fetchone()
        if existing:
            if it.get("image") and not existing["image_url"]:  # backfill images for items fetched before v0.5
                conn.execute("UPDATE source_items SET image_url=? WHERE id=?", (it["image"], existing["id"]))
            continue
        if conn.execute("SELECT 1 FROM source_items WHERE source_id=? AND content_hash=?", (source_id, chash)).fetchone():
            continue  # same publisher re-posting same headline at another URL
        cur = conn.execute(
            """INSERT INTO source_items(source_id,title,url,canonical_url,published_at,retrieved_at,author,snippet,content_hash,data_origin,image_url)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (source_id, it["title"], it["url"], canon, it["published"], retrieved, it["author"], it["snippet"], chash, origin, it.get("image")))
        new += 1
        cluster_item(conn, cur.lastrowid)
    return seen, new, rejected


def cluster_item(conn, item_id):
    """Attach item to an existing event if headline is near-identical in wording, else create event.
    Deliberately conservative: distinct developments on the same broad topic are NOT merged.
    Admin can merge/split manually."""
    it = conn.execute("SELECT * FROM source_items WHERE id=?", (item_id,)).fetchone()
    ref = it["published_at"] or it["retrieved_at"]
    ref_dt = datetime.strptime(ref, "%Y-%m-%dT%H:%M:%SZ")
    lo = (ref_dt - timedelta(days=CLUSTER_WINDOW_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    mine = tokens(it["title"])
    best, best_score = None, 0.0
    cands = conn.execute(
        "SELECT id, headline FROM news_events WHERE merged_into IS NULL AND status!='rejected' AND first_seen_at>=? ORDER BY id DESC",
        (lo,)).fetchall()
    for ev in cands:
        titles = [ev["headline"]] + [r["title"] for r in conn.execute(
            "SELECT title FROM source_items WHERE event_id=?", (ev["id"],))]
        for title in titles:  # compare against each member headline, not a union (avoids drift)
            t = tokens(title)
            j = jaccard(mine, t)
            if j >= CLUSTER_MIN_JACCARD and len(mine & t) >= CLUSTER_MIN_SHARED and j > best_score:
                best, best_score = ev["id"], j
    if best is None:
        cur = conn.execute(
            "INSERT INTO news_events(headline,event_date,first_seen_at,data_origin) VALUES(?,?,?,?)",
            (it["title"], (it["published_at"] or it["retrieved_at"])[:10], now_iso(), it["data_origin"]))
        best = cur.lastrowid
    conn.execute("UPDATE source_items SET event_id=? WHERE id=?", (best, item_id))
    classify_event(conn, best)
    return best


# ---------- mapping & scoring ----------
@functools.lru_cache(maxsize=None)
def _kw_pattern(kw):
    kw = kw.strip().lower()
    body = re.escape(kw)
    tail = r"(?![a-z0-9])" if len(kw) <= 4 else ""
    return re.compile(r"(?<![a-z0-9])" + body + tail)


NOISE_TERMS = ["ipl", "cricket", "t20", "fifa", "premier league", "box office", "bollywood", "film review", "web series",
               "celebrity", "horoscope", "recipe", "fashion", "wedding", "stocks to buy", "share price", "target price",
               "sensex today", "nifty today", "stock market today", "gold rate", "petrol price today", "mutual fund",
               "ipo allotment", "q1 results", "q2 results", "q3 results", "q4 results", "astrology", "murder", "stabbed",
               "lifestyle", "viral video", "trailer"]


def noise_hits(text):
    text = " " + (text or "").lower() + " "
    return [k for k in NOISE_TERMS if _kw_pattern(k).search(text)]


def map_text_to_topics(conn, text):
    """Return list of (topic_id, confidence, matched_terms) sorted high->low. Heuristic keyword method.
    Keywords marked '~' are weak (count half). Diminishing returns: weight 1 -> .30, 2 -> .51, 3 -> .66, capped .9."""
    text = " " + (text or "").lower() + " "
    res = []
    for t in conn.execute("SELECT id, keywords FROM syllabus_topics"):
        weight, hits = 0.0, []
        for k in (t["keywords"] or "").split("|"):
            if not k:
                continue
            weak = k.startswith("~")
            term = k.lstrip("~")
            if _kw_pattern(term).search(text):
                weight += 0.5 if weak else 1.0
                hits.append(term)
        if hits:
            conf = min(0.9, 1 - 0.7 ** weight)
            res.append((t["id"], round(conf, 2), hits))
    return sorted(res, key=lambda r: -r[1])


def get_weights(conn):
    return DEFAULT_WEIGHTS


def classify_event(conn, event_id):
    rows = conn.execute(
        """SELECT si.title, si.snippet, si.published_at, si.retrieved_at, s.reliability, s.id sid
           FROM source_items si JOIN sources s ON s.id=si.source_id WHERE si.event_id=?""", (event_id,)).fetchall()
    if not rows:
        return
    text = " ".join(f"{r['title']} {r['snippet'] or ''}" for r in rows)
    mapped = map_text_to_topics(conn, text)
    conn.execute("DELETE FROM event_topic_mappings WHERE event_id=? AND method='keyword'", (event_id,))
    kept = [m for m in mapped if m[1] >= MAP_THRESHOLD][:4]
    for i, (tid, conf, hits) in enumerate(kept):
        conn.execute(
            "INSERT OR REPLACE INTO event_topic_mappings(event_id,topic_id,confidence,is_primary,matched_terms,method) VALUES(?,?,?,?,?,'keyword')",
            (event_id, tid, conf, 1 if i == 0 else 0, ", ".join(hits)))
    top = kept[0][1] if kept else 0.0
    distinct_sources = len({r["sid"] for r in rows})  # repeated coverage by ONE publisher adds nothing
    rel = max(RELIABILITY.get(r["reliability"], 0.4) for r in rows)
    newest = max((r["published_at"] or r["retrieved_at"]) for r in rows)
    age_days = max(0, (datetime.now(timezone.utc) - datetime.strptime(newest, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)).days)
    recency = max(0.0, 1 - age_days / 14)
    corrob = min(1.0, (distinct_sources - 1) / 3)
    w = get_weights(conn)
    parts = {"syllabus": top, "reliability": rel, "corroboration": corrob, "recency": recency}
    score = round(sum(parts[k] * w[k] for k in w) * 100, 1)
    noisy = noise_hits(text)
    is_noise = 1 if (noisy and top < 0.60) else 0  # strong syllabus evidence outweighs a stray noise word
    if is_noise:
        score = round(score * 0.4, 1)
    needs_review = 1 if (not kept or top < REVIEW_BELOW or is_noise) else 0
    conn.execute("UPDATE news_events SET relevance_score=?, score_breakdown=?, needs_review=?, noise=? WHERE id=?",
                 (score, json.dumps({"parts": {k: round(v, 2) for k, v in parts.items()}, "weights": w,
                                     "distinct_sources": distinct_sources, "noise_terms": noisy}), needs_review, is_noise, event_id))


# ---------- jobs ----------
def fetch_parse(src):
    """Network + parse only (thread-safe, no DB). Returns (items, error)."""
    try:
        if src["access_method"] != "rss" or not src["feed_url"]:
            raise ValueError("No automated connector for this source (not implemented).")
        return parse_feed(http_get(src["feed_url"])), None
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"


def fetch_many(sources, workers=6):
    from concurrent.futures import ThreadPoolExecutor
    srcs = [dict(s) for s in sources]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(zip(srcs, ex.map(fetch_parse, srcs)))


def record_result(conn, src, items, err, t0, kind="rss_fetch"):
    """Store items (if any) and write the job + source status. Returns (job_id, status, seen, new, err)."""
    seen = new = 0
    status = "succeeded"
    if err is None:
        seen, new, _ = store_items(conn, src["id"], items, "live")
        conn.execute("UPDATE sources SET last_success_at=?, last_error=NULL, verification='working' WHERE id=?", (now_iso(), src["id"]))
    else:
        status = "failed"
        conn.execute("UPDATE sources SET last_error=?, verification='failing' WHERE id=?", (err, src["id"]))
    cur = conn.execute(
        "INSERT INTO fetch_jobs(kind,source_id,status,started_at,finished_at,duration_ms,items_seen,items_new,error) VALUES(?,?,?,?,?,?,?,?,?)",
        (kind, src["id"], status, now_iso(), now_iso(), int((time.time() - t0) * 1000), seen, new, err))
    conn.commit()
    return cur.lastrowid, status, seen, new, err


def run_fetch_job(conn, source_id, kind="rss_fetch"):
    src = conn.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
    t0 = time.time()
    items, err = fetch_parse(src)
    return record_result(conn, src, items, err, t0, kind)


def run_all_active(conn, kind="rss_fetch"):
    srcs = conn.execute("SELECT * FROM sources WHERE active=1 AND access_method='rss'").fetchall()
    t0 = time.time()
    return [record_result(conn, s, items, err, t0, kind) for s, (items, err) in fetch_many(srcs)]


def quickstart_run(conn):
    """Fetch every RSS source once (in parallel). Sources that respond are activated; failures stay inactive.
    Returns (working_names, [(name, error)], new_items)."""
    srcs = conn.execute("SELECT * FROM sources WHERE access_method='rss' AND feed_url!=''").fetchall()
    t0 = time.time()
    ok, bad, new = [], [], 0
    for s, (items, err) in fetch_many(srcs):
        _, status, _, n, e = record_result(conn, s, items, err, t0)
        if status == "succeeded":
            conn.execute("UPDATE sources SET active=1 WHERE id=?", (s["id"],))
            ok.append(s["name"]); new += n
        else:
            conn.execute("UPDATE sources SET active=0 WHERE id=?", (s["id"],))
            bad.append((s["name"], e))
    conn.commit()
    return ok, bad, new


def due_sources(conn, now_ts=None):
    """Active RSS sources whose last attempt is older than their fetch interval."""
    now_ts = now_ts or time.time()
    out = []
    for s in conn.execute("SELECT * FROM sources WHERE active=1 AND access_method='rss'").fetchall():
        last = conn.execute("SELECT started_at FROM fetch_jobs WHERE source_id=? ORDER BY id DESC LIMIT 1", (s["id"],)).fetchone()
        if not last:
            out.append(s); continue
        last_ts = datetime.strptime(last["started_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
        if now_ts - last_ts >= max(15, s["fetch_interval_min"] or 60) * 60:
            out.append(s)
    return out


def reclassify_all(conn):
    ids = [r["id"] for r in conn.execute("SELECT id FROM news_events WHERE merged_into IS NULL")]
    for i in ids:
        classify_event(conn, i)
    conn.commit()
    return len(ids)
