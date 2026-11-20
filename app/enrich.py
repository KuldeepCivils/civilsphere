"""Wider context for each news event, from open/public sources only.

1. Related coverage: Google News' public RSS search for the headline. We keep ONLY headline, outlet name and link of other
   reports on the same story (metadata, like any feed reader), never article text.
2. Reference background: Wikipedia's public API (text is CC BY-SA 4.0; shown with attribution and a link).

Nothing here is scraped from paywalled pages, nothing bypasses a block, and any failure is simply "no extra context".
Both are passed to the AI as untrusted reference text, and shown to the reader with links so they can verify.
"""
import json
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, quote_plus

from . import ingest
from .ingest import now_iso

RETRY_EMPTY_AFTER_HOURS = 6
STOP = {"The", "A", "An", "In", "On", "At", "For", "Of", "To", "And", "As", "With", "By", "From", "After", "Before", "Over", "Under", "How", "Why", "What", "Who", "When", "Is", "Are", "Was", "Were", "New", "Says", "Said"}


def proper_nouns(headline):
    """Capitalised words/phrases in a headline, used as a focused Wikipedia query (avoids random hits for long headlines)."""
    words = re.findall(r"[A-Za-z][A-Za-z'\-]+", headline)
    out, cur = [], []
    for i, w in enumerate(words):
        if w[0].isupper() and w not in STOP:
            cur.append(w)
        else:
            if cur:
                out.append(" ".join(cur))
            cur = []
    if cur:
        out.append(" ".join(cur))
    return out[:4]


def related_coverage(headline, own_urls=()):
    url = f"https://news.google.com/rss/search?q={quote_plus(headline)}&hl=en-IN&gl=IN&ceid=IN:en"
    items = ingest.parse_feed(ingest.http_get(url))
    own = {ingest.canonical_url(u) for u in own_urls}
    seen, out = set(), []
    for it in items:
        title = it["title"].strip()
        pub = ""
        if " - " in title:
            title, pub = title.rsplit(" - ", 1)
        key = re.sub(r"\W+", " ", title.lower()).strip()
        if not key or key in seen or key == re.sub(r"\W+", " ", headline.lower()).strip() or ingest.canonical_url(it["url"]) in own:
            continue
        seen.add(key)
        out.append({"title": title[:200], "publisher": pub[:80], "url": it["url"]})
        if len(out) >= 8:
            break
    return out


def _wiki_get(url):
    """Wikipedia asks API users to go gently: retry once after a 429, then give up quietly."""
    import requests
    for attempt in range(2):
        try:
            return ingest.http_get(url)
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 429 and attempt == 0:
                try:
                    wait = float(e.response.headers.get("retry-after", "5"))
                except ValueError:
                    wait = 5
                time.sleep(min(max(wait, 3), 20))
                continue
            raise


def wiki_context(headline, limit=2):
    nouns = proper_nouns(headline)
    if not nouns:
        return []
    q = " ".join(nouns)
    data = json.loads(_wiki_get(
        "https://en.wikipedia.org/w/api.php?action=query&list=search&format=json&srlimit=4&srsearch=" + quote_plus(q)))
    head_tokens = {t for t in re.findall(r"[a-z]{4,}", headline.lower())}
    out = []
    for hit in data.get("query", {}).get("search", []):
        title = hit["title"]
        if not (set(re.findall(r"[a-z]{4,}", title.lower())) & head_tokens):  # page title must share a real word with the headline
            continue
        s = json.loads(_wiki_get("https://en.wikipedia.org/api/rest_v1/page/summary/" + quote(title.replace(" ", "_"), safe="")))
        if s.get("type") == "disambiguation" or not s.get("extract"):
            continue
        out.append({"title": s.get("title", title), "extract": s["extract"][:3000],
                    "url": (s.get("content_urls", {}).get("desktop", {}) or {}).get("page", "https://en.wikipedia.org/wiki/" + quote(title.replace(" ", "_")))})
        if len(out) >= limit:
            break
    return out


def enrich_event(conn, event_id):
    e = conn.execute("SELECT headline FROM news_events WHERE id=?", (event_id,)).fetchone()
    if not e:
        return False
    urls = [r["url"] for r in conn.execute("SELECT url FROM source_items WHERE event_id=?", (event_id,))]
    cov, wiki, errs = [], [], []
    for fn, args, dest in ((related_coverage, (e["headline"], urls), cov), (wiki_context, (e["headline"],), wiki)):
        try:
            dest.extend(fn(*args))
        except Exception as ex:  # noqa: BLE001 - extra context is optional
            errs.append(f"{fn.__name__}: {type(ex).__name__}: {str(ex)[:100]}")
    conn.execute("INSERT OR REPLACE INTO event_context(event_id,fetched_at,coverage,wiki,error) VALUES(?,?,?,?,?)",
                 (event_id, now_iso(), json.dumps(cov), json.dumps(wiki), "; ".join(errs) or None))
    conn.commit()
    return bool(cov or wiki)


def pending_ids(conn, limit, days=14):
    lo = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    retry = (datetime.now(timezone.utc) - timedelta(hours=RETRY_EMPTY_AFTER_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    retry_err = (datetime.now(timezone.utc) - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return [r["id"] for r in conn.execute(
        """SELECT e.id FROM news_events e JOIN event_topic_mappings m ON m.event_id=e.id AND m.is_primary=1
           LEFT JOIN event_context c ON c.event_id=e.id
           WHERE e.event_date>=? AND e.merged_into IS NULL AND e.status!='rejected' AND e.noise=0
             AND (c.event_id IS NULL OR (c.error IS NOT NULL AND c.fetched_at<?) OR (c.coverage='[]' AND c.wiki='[]' AND c.fetched_at<?))
           ORDER BY e.relevance_score DESC LIMIT ?""", (lo, retry_err, retry, limit))]


def enrich_pending(conn, limit=25, pause=1.5):
    done = 0
    for eid in pending_ids(conn, limit):
        enrich_event(conn, eid)
        done += 1
        time.sleep(pause)
    return done


def load_context(conn, event_id):
    r = conn.execute("SELECT * FROM event_context WHERE event_id=?", (event_id,)).fetchone()
    if not r:
        return {"coverage": [], "wiki": []}
    return {"coverage": json.loads(r["coverage"] or "[]"), "wiki": json.loads(r["wiki"] or "[]")}
