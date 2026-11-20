"""Seed syllabus and the source registry. Sources are seeded INACTIVE and 'untested':
nothing is claimed to work until an admin tests it. Feed URLs below are commonly published
feed locations but MUST be verified with the 'Test' button; they are not guaranteed."""
from . import db
from .syllabus_data import PAPERS, TOPICS

# (name, category, base_url, feed_url, access_method, rights, reliability, notes)
SEED_SOURCES = [
    ("PIB (Press Information Bureau)", "Government", "https://pib.gov.in", "https://pib.gov.in/RssMain.aspx?ModId=6&Lang=1&Regid=3",
     "rss", "metadata_only", "official", "Official government releases. Verify feed URL via Test."),
    ("The Hindu - National", "Newspaper", "https://www.thehindu.com", "https://www.thehindu.com/news/national/feeder/default.rss",
     "rss", "metadata_only", "high", "Publisher RSS; headline+summary only. Respect publisher terms/paywall."),
    ("The Hindu - Editorial", "Newspaper", "https://www.thehindu.com", "https://www.thehindu.com/opinion/editorial/feeder/default.rss",
     "rss", "metadata_only", "high", "Publisher RSS; link-only use."),
    ("The Indian Express - India", "Newspaper", "https://indianexpress.com", "https://indianexpress.com/section/india/feed/",
     "rss", "metadata_only", "high", "Publisher RSS; headline+summary only."),
    ("The Indian Express - Explained", "Newspaper", "https://indianexpress.com", "https://indianexpress.com/section/explained/feed/",
     "rss", "metadata_only", "high", "Publisher RSS; link-only use."),
    ("Down To Earth", "Research/Magazine", "https://www.downtoearth.org.in", "https://www.downtoearth.org.in/rss/all",
     "rss", "metadata_only", "high", "Environment/science. Verify feed via Test."),
    ("The Hindu - International", "Newspaper", "https://www.thehindu.com", "https://www.thehindu.com/news/international/feeder/default.rss", "rss", "metadata_only", "high", "Feed address written from general knowledge and NOT verified: press Quick start to test it from your PC. "),
    ("The Hindu - Economy", "Newspaper", "https://www.thehindu.com", "https://www.thehindu.com/business/Economy/feeder/default.rss", "rss", "metadata_only", "high", "Feed address written from general knowledge and NOT verified: press Quick start to test it from your PC. "),
    ("The Hindu - Science", "Newspaper", "https://www.thehindu.com", "https://www.thehindu.com/sci-tech/science/feeder/default.rss", "rss", "metadata_only", "high", "Feed address written from general knowledge and NOT verified: press Quick start to test it from your PC. "),
    ("The Indian Express - Editorials", "Newspaper", "https://indianexpress.com", "https://indianexpress.com/section/opinion/editorials/feed/", "rss", "metadata_only", "high", "Feed address written from general knowledge and NOT verified: press Quick start to test it from your PC. "),
    ("Times of India - Top Stories", "Newspaper", "https://timesofindia.indiatimes.com", "https://timesofindia.indiatimes.com/rssfeedstopstories.cms", "rss", "metadata_only", "medium", "Feed address written from general knowledge and NOT verified: press Quick start to test it from your PC. "),
    ("Times of India - India", "Newspaper", "https://timesofindia.indiatimes.com", "https://timesofindia.indiatimes.com/rssfeeds/-2128936835.cms", "rss", "metadata_only", "medium", "Feed address written from general knowledge and NOT verified: press Quick start to test it from your PC. "),
    ("Economic Times - Top Stories", "Business", "https://economictimes.indiatimes.com", "https://economictimes.indiatimes.com/rssfeedstopstories.cms", "rss", "metadata_only", "high", "Feed address written from general knowledge and NOT verified: press Quick start to test it from your PC. "),
    ("Economic Times - Economy", "Business", "https://economictimes.indiatimes.com", "https://economictimes.indiatimes.com/news/economy/rssfeeds/1373380680.cms", "rss", "metadata_only", "high", "Feed address written from general knowledge and NOT verified: press Quick start to test it from your PC. "),
    ("Moneycontrol - Latest", "Business", "https://www.moneycontrol.com", "https://www.moneycontrol.com/rss/latestnews.xml", "rss", "metadata_only", "medium", "Feed address written from general knowledge and NOT verified: press Quick start to test it from your PC. "),
    ("Moneycontrol - Economy", "Business", "https://www.moneycontrol.com", "https://www.moneycontrol.com/rss/economy.xml", "rss", "metadata_only", "medium", "Feed address written from general knowledge and NOT verified: press Quick start to test it from your PC. "),
    ("Business Standard - Economy & Policy", "Business", "https://www.business-standard.com", "https://www.business-standard.com/rss/economy-policy-102.rss", "rss", "metadata_only", "high", "Feed address written from general knowledge and NOT verified: press Quick start to test it from your PC. "),
    ("Mint - Economy", "Business", "https://www.livemint.com", "https://www.livemint.com/rss/economy", "rss", "metadata_only", "high", "Feed address written from general knowledge and NOT verified: press Quick start to test it from your PC. "),
    ("Financial Express - Economy", "Business", "https://www.financialexpress.com", "https://www.financialexpress.com/economy/feed/", "rss", "metadata_only", "high", "Feed address written from general knowledge and NOT verified: press Quick start to test it from your PC. "),
    ("BusinessLine - Economy", "Business", "https://www.thehindubusinessline.com", "https://www.thehindubusinessline.com/economy/feeder/default.rss", "rss", "metadata_only", "high", "Feed address written from general knowledge and NOT verified: press Quick start to test it from your PC. "),
    ("Hindustan Times - India", "Newspaper", "https://www.hindustantimes.com", "https://www.hindustantimes.com/feeds/rss/india-news/rssfeed.xml", "rss", "metadata_only", "medium", "Feed address written from general knowledge and NOT verified: press Quick start to test it from your PC. "),
    ("Deccan Herald - National", "Newspaper", "https://www.deccanherald.com", "https://www.deccanherald.com/rss/national.rss", "rss", "metadata_only", "medium", "Feed address written from general knowledge and NOT verified: press Quick start to test it from your PC. "),
    ("RBI - Press Releases", "Government", "https://www.rbi.org.in", "https://rbi.org.in/pressreleases_rss.xml", "rss", "metadata_only", "official", "Feed address written from general knowledge and NOT verified: press Quick start to test it from your PC. "),
    ("SEBI - Press Releases", "Government", "https://www.sebi.gov.in", "https://www.sebi.gov.in/sebirss.xml", "rss", "metadata_only", "official", "Feed address written from general knowledge and NOT verified: press Quick start to test it from your PC. "),
    ("ORF - Research & Analysis", "Research/Magazine", "https://www.orfonline.org", "https://www.orfonline.org/feed", "rss", "metadata_only", "high", "Feed address written from general knowledge and NOT verified: press Quick start to test it from your PC. "),
    ("Mongabay India", "Research/Magazine", "https://india.mongabay.com", "https://india.mongabay.com/feed/", "rss", "metadata_only", "high", "Feed address written from general knowledge and NOT verified: press Quick start to test it from your PC. "),
    ("BBC - India", "International", "https://www.bbc.com", "https://feeds.bbci.co.uk/news/world/asia/india/rss.xml", "rss", "metadata_only", "high", "Feed address written from general knowledge and NOT verified: press Quick start to test it from your PC. "),
    ("Al Jazeera - All", "International", "https://www.aljazeera.com", "https://www.aljazeera.com/xml/rss/all.xml", "rss", "metadata_only", "medium", "Feed address written from general knowledge and NOT verified: press Quick start to test it from your PC. "),
    ("Manual links (EPW, monthly magazines, others)", "Magazine", "https://www.epw.in", "", "manual", "metadata_only", "high",
     "EPW has no public feed and is partly paywalled; monthly magazines are copyrighted. Add only titles + links (+ your own note) on the Import links page. Nothing is scraped."),
]


def seed_syllabus():
    with db.session() as c:
        if c.execute("SELECT COUNT(*) FROM syllabus_papers").fetchone()[0]:
            return False
        for i, (code, stage, name, wording) in enumerate(PAPERS):
            c.execute("INSERT INTO syllabus_papers(code,exam_stage,name,official_wording,sort_order) VALUES(?,?,?,?,?)",
                      (code, stage, name, wording, i))
            pid = c.execute("SELECT id FROM syllabus_papers WHERE code=?", (code,)).fetchone()[0]
            for j, (tname, official, kws) in enumerate(TOPICS[code]):
                c.execute("INSERT INTO syllabus_topics(paper_id,name,official_wording,keywords,sort_order) VALUES(?,?,?,?,?)",
                          (pid, tname, official, "|".join(kws), j))
        return True


def seed_sources():
    """Insert any registry source that is not there yet (matched by name). Existing rows are never changed."""
    added = 0
    with db.session() as c:
        # retired placeholder (removed in v0.13); only deleted when it never held any items
        c.execute("DELETE FROM sources WHERE name='LBSNAA API' AND NOT EXISTS (SELECT 1 FROM source_items WHERE source_id=sources.id)")
        have = {r[0] for r in c.execute("SELECT name FROM sources")}
        for n, cat, base, feed, meth, rights, rel, notes in SEED_SOURCES:
            if n in have:
                continue
            c.execute("""INSERT INTO sources(name,category,base_url,feed_url,access_method,content_rights,
                         reliability,access_notes,active,verification) VALUES(?,?,?,?,?,?,?,?,0,'untested')""",
                      (n, cat, base, feed, meth, rights, rel, notes))
            added += 1
    return added


def sync_keywords():
    """When the keyword lists change (KEYWORDS_VERSION), refresh them in the database and re-map every event."""
    from . import ingest
    from .syllabus_data import KEYWORDS_VERSION
    with db.session() as c:
        cur = c.execute("PRAGMA user_version").fetchone()[0]
        if cur == int(KEYWORDS_VERSION):
            return False
        for code, topics in TOPICS.items():
            for name, _official, kws in topics:
                c.execute("""UPDATE syllabus_topics SET keywords=? WHERE name=? AND paper_id=
                             (SELECT id FROM syllabus_papers WHERE code=?)""", ("|".join(kws), name, code))
        ingest.reclassify_all(c)
        c.execute(f"PRAGMA user_version={int(KEYWORDS_VERSION)}")
        c.commit()
        return True


def seed_all():
    db.init_db()
    seed_syllabus()
    seed_sources()
    from . import pyq
    with db.session() as c:
        pyq.sync_bank(c)


def sync_keywords_background():
    """Re-mapping runs after the site is already up, so a big database can never delay start-up."""
    import threading

    def _run():
        try:
            sync_keywords()
        except Exception:  # noqa: BLE001 - retried at next start
            pass
    threading.Thread(target=_run, daemon=True).start()
