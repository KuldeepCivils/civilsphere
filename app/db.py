import sqlite3
from contextlib import contextmanager
from . import config

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS syllabus_papers (
  id INTEGER PRIMARY KEY, code TEXT UNIQUE NOT NULL, exam_stage TEXT NOT NULL,
  name TEXT NOT NULL, official_wording TEXT, sort_order INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS syllabus_topics (
  id INTEGER PRIMARY KEY, paper_id INTEGER NOT NULL REFERENCES syllabus_papers(id),
  parent_id INTEGER REFERENCES syllabus_topics(id), name TEXT NOT NULL,
  official_wording TEXT, keywords TEXT DEFAULT '', sort_order INTEGER DEFAULT 0,
  UNIQUE(paper_id, name));
CREATE INDEX IF NOT EXISTS ix_topics_paper ON syllabus_topics(paper_id);

CREATE TABLE IF NOT EXISTS sources (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL,
  base_url TEXT, feed_url TEXT, access_method TEXT NOT NULL DEFAULT 'rss',
  access_notes TEXT, language TEXT DEFAULT 'en', reliability TEXT DEFAULT 'unrated',
  content_rights TEXT NOT NULL DEFAULT 'metadata_only',
  active INTEGER NOT NULL DEFAULT 0, fetch_interval_min INTEGER DEFAULT 60,
  verification TEXT NOT NULL DEFAULT 'untested',  -- untested | working | failing
  last_success_at TEXT, last_error TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(name, feed_url));

CREATE TABLE IF NOT EXISTS fetch_jobs (
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL, source_id INTEGER REFERENCES sources(id),
  status TEXT NOT NULL, started_at TEXT, finished_at TEXT, duration_ms INTEGER,
  items_seen INTEGER DEFAULT 0, items_new INTEGER DEFAULT 0, error TEXT,
  data_origin TEXT NOT NULL DEFAULT 'live');

CREATE TABLE IF NOT EXISTS source_items (
  id INTEGER PRIMARY KEY, source_id INTEGER NOT NULL REFERENCES sources(id),
  title TEXT NOT NULL, url TEXT NOT NULL, canonical_url TEXT NOT NULL UNIQUE,
  published_at TEXT, retrieved_at TEXT NOT NULL, author TEXT, snippet TEXT,
  content_hash TEXT, data_origin TEXT NOT NULL DEFAULT 'live', event_id INTEGER, image_url TEXT);
CREATE INDEX IF NOT EXISTS ix_items_event ON source_items(event_id);
CREATE INDEX IF NOT EXISTS ix_items_pub ON source_items(published_at);

CREATE TABLE IF NOT EXISTS news_events (
  id INTEGER PRIMARY KEY, headline TEXT NOT NULL, event_date TEXT,
  first_seen_at TEXT NOT NULL, relevance_score REAL DEFAULT 0, score_breakdown TEXT,
  status TEXT NOT NULL DEFAULT 'auto',  -- auto | reviewed | rejected
  needs_review INTEGER DEFAULT 0, data_origin TEXT NOT NULL DEFAULT 'live',
  merged_into INTEGER REFERENCES news_events(id), noise INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS ix_events_date ON news_events(event_date);

CREATE TABLE IF NOT EXISTS event_topic_mappings (
  id INTEGER PRIMARY KEY, event_id INTEGER NOT NULL REFERENCES news_events(id),
  topic_id INTEGER NOT NULL REFERENCES syllabus_topics(id), confidence REAL NOT NULL,
  is_primary INTEGER NOT NULL DEFAULT 0, matched_terms TEXT,
  method TEXT NOT NULL DEFAULT 'keyword', UNIQUE(event_id, topic_id));

CREATE TABLE IF NOT EXISTS reports (
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL, period_start TEXT, period_end TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS report_versions (
  id INTEGER PRIMARY KEY, report_id INTEGER NOT NULL REFERENCES reports(id),
  version INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'generated',
  body_html TEXT NOT NULL, generator TEXT NOT NULL, input_event_count INTEGER,
  warnings TEXT, generated_at TEXT NOT NULL, UNIQUE(report_id, version));

CREATE TABLE IF NOT EXISTS ai_notes (
  id INTEGER PRIMARY KEY, event_id INTEGER NOT NULL UNIQUE REFERENCES news_events(id),
  model TEXT NOT NULL, prompt_version TEXT NOT NULL, generated_at TEXT NOT NULL,
  key_points TEXT NOT NULL, static_linkage TEXT NOT NULL, mains_theme TEXT, overview TEXT, summary TEXT, background TEXT, perspective TEXT, about TEXT, info_table TEXT, facts TEXT, sections TEXT, prelims TEXT,
  input_tokens INTEGER, output_tokens INTEGER, status TEXT NOT NULL DEFAULT 'unreviewed');

CREATE TABLE IF NOT EXISTS event_context (
  event_id INTEGER PRIMARY KEY REFERENCES news_events(id), fetched_at TEXT NOT NULL,
  coverage TEXT NOT NULL DEFAULT '[]', wiki TEXT NOT NULL DEFAULT '[]', error TEXT);

CREATE TABLE IF NOT EXISTS quizzes (
  id INTEGER PRIMARY KEY, quiz_date TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL, model TEXT NOT NULL, prompt_version TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS quiz_questions (
  id INTEGER PRIMARY KEY, quiz_id INTEGER NOT NULL REFERENCES quizzes(id) ON DELETE CASCADE,
  event_id INTEGER REFERENCES news_events(id), kind TEXT NOT NULL, discipline TEXT, concept TEXT,
  question TEXT NOT NULL, options TEXT, answer_idx INTEGER, explanation TEXT, model_points TEXT, sort_order INTEGER NOT NULL DEFAULT 0);

CREATE TABLE IF NOT EXISTS pyq (
  id INTEGER PRIMARY KEY, pkey TEXT NOT NULL UNIQUE, exam TEXT NOT NULL, year INTEGER NOT NULL, paper TEXT, question TEXT NOT NULL,
  options TEXT, answer_idx INTEGER, explanation TEXT, keywords TEXT NOT NULL, source TEXT NOT NULL, created_at TEXT NOT NULL, subject TEXT, topic TEXT);

CREATE TABLE IF NOT EXISTS visitors (
  id TEXT PRIMARY KEY, first_seen INTEGER NOT NULL, last_seen INTEGER NOT NULL,
  visits INTEGER NOT NULL DEFAULT 0, pageviews INTEGER NOT NULL DEFAULT 0, seconds INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS visits (
  id INTEGER PRIMARY KEY, visitor_id TEXT NOT NULL REFERENCES visitors(id), started_at INTEGER NOT NULL,
  last_seen INTEGER NOT NULL, pageviews INTEGER NOT NULL DEFAULT 0, seconds INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS ix_visits_visitor ON visits(visitor_id, id);

CREATE TABLE IF NOT EXISTS bulletin_scripts (
  id INTEGER PRIMARY KEY, bdate TEXT NOT NULL, pos INTEGER NOT NULL, kind TEXT NOT NULL, event_id INTEGER, headline TEXT, paper TEXT,
  en_text TEXT NOT NULL, UNIQUE(bdate,pos));
CREATE TABLE IF NOT EXISTS bulletin_audio (
  id INTEGER PRIMARY KEY, bdate TEXT NOT NULL, lang TEXT NOT NULL, pos INTEGER NOT NULL, kind TEXT NOT NULL, event_id INTEGER, headline TEXT,
  text TEXT NOT NULL, seconds REAL NOT NULL, file TEXT NOT NULL, UNIQUE(bdate,lang,pos));
CREATE TABLE IF NOT EXISTS bulletins (
  bdate TEXT NOT NULL, lang TEXT NOT NULL, status TEXT NOT NULL, total_seconds REAL, created_at TEXT, error TEXT, PRIMARY KEY(bdate,lang));

CREATE TABLE IF NOT EXISTS admin_audit_logs (
  id INTEGER PRIMARY KEY, at TEXT DEFAULT CURRENT_TIMESTAMP, action TEXT NOT NULL, detail TEXT);
"""


def connect():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


@contextmanager
def session():
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with session() as c:
        c.executescript(SCHEMA)
        cols = {r[1] for r in c.execute("PRAGMA table_info(source_items)")}
        ecols = {r[1] for r in c.execute("PRAGMA table_info(news_events)")}
        acols = {r[1] for r in c.execute("PRAGMA table_info(ai_notes)")}
        pcols = {r[1] for r in c.execute("PRAGMA table_info(pyq)")}
        for col in ("subject", "topic"):  # migration: v0.25 subject/topic of past questions
            if col not in pcols:
                c.execute(f"ALTER TABLE pyq ADD COLUMN {col} TEXT")
        for col in ("background", "perspective", "about", "info_table", "facts", "sections", "prelims"):  # migration: v0.14 fields
            if col not in acols:
                c.execute(f"ALTER TABLE ai_notes ADD COLUMN {col} TEXT")
        if "summary" not in acols:  # migration: fuller main-news summary added in v0.12
            c.execute("ALTER TABLE ai_notes ADD COLUMN summary TEXT")
        if "overview" not in acols:  # migration: bullet overview added in v0.10
            c.execute("ALTER TABLE ai_notes ADD COLUMN overview TEXT")
        if "noise" not in ecols:  # migration for databases created before v0.9
            c.execute("ALTER TABLE news_events ADD COLUMN noise INTEGER NOT NULL DEFAULT 0")
        if "image_url" not in cols:  # migration for databases created before v0.5
            c.execute("ALTER TABLE source_items ADD COLUMN image_url TEXT")
        c.execute("INSERT OR REPLACE INTO schema_meta VALUES('version', ?)", (str(SCHEMA_VERSION),))


def audit(conn, action, detail=""):
    conn.execute("INSERT INTO admin_audit_logs(action, detail) VALUES(?,?)", (action, detail))
