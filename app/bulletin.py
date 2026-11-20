"""Daily audio news bulletin (about 30 minutes) in English, Hindi and regional languages.

Pipeline: pick the day's top UPSC-relevant stories -> write a short spoken script for each (about 30 s, never more than 45 s)
-> translate the scripts -> turn each into an MP3 with a free neural voice (edge-tts, gTTS as fallback).
Stories are separate MP3 files played as a playlist, so the player can show chapters and jump between stories.
Only public news text is sent to the voice service; never put personal data into a bulletin."""
import asyncio
import json
import os
import re
import shutil
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from . import ai, config
from .ingest import now_iso

TARGET_S = 30 * 60          # total bulletin length
WPS = 2.4                   # spoken words per second (about 145 words a minute)
ITEM_WORDS = 72             # about 30 s
MAX_WORDS = 105             # about 44 s: hard ceiling, used only for exceptionally important stories
BATCH = 6

# code: (English name, native name, edge-tts voice, gTTS code)
LANGS = {
    "en": ("English", "English", "en-IN-NeerjaNeural", "en"),
    "hi": ("Hindi", "हिन्दी", "hi-IN-SwaraNeural", "hi"),
    "gu": ("Gujarati", "ગુજરાતી", "gu-IN-DhwaniNeural", "gu"),
    "mr": ("Marathi", "मराठी", "mr-IN-AarohiNeural", "mr"),
    "ta": ("Tamil", "தமிழ்", "ta-IN-PallaviNeural", "ta"),
    "te": ("Telugu", "తెలుగు", "te-IN-ShrutiNeural", "te"),
    "kn": ("Kannada", "ಕನ್ನಡ", "kn-IN-SapnaNeural", "kn"),
    "ml": ("Malayalam", "മലയാളം", "ml-IN-SobhanaNeural", "ml"),
    "bn": ("Bengali", "বাংলা", "bn-IN-TanishaaNeural", "bn"),
    "ur": ("Urdu", "اردو", "ur-IN-GulNeural", "ur"),
    "pa": ("Punjabi", "ਪੰਜਾਬੀ", "", "pa"),
}
LEADS = {
    "GS1": "General Studies Paper One. History, geography and society.",
    "GS2": "General Studies Paper Two. Polity, governance and international relations.",
    "GS3": "General Studies Paper Three. Economy, science, environment and security.",
    "GS4": "General Studies Paper Four. Ethics and integrity.",
}
STATUS = {}   # (date, lang) -> {"phase","done","total","error","running"}
_LOCK = threading.Lock()


# ------------------------------------------------------------------ text helpers
def words(t):
    return len(re.findall(r"\S+", t or ""))


def est_seconds(t):
    return words(t) / WPS + 0.6


def cap_words(text, limit=MAX_WORDS):
    """Trim to at most `limit` words, ending on a sentence boundary when possible."""
    text = re.sub(r"\s+", " ", (text or "").replace("*", "").replace("#", "")).strip()
    toks = text.split(" ")
    if len(toks) <= limit:
        return text
    cut = " ".join(toks[:limit])
    end = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "))
    if end > len(cut) * 0.55:
        return cut[:end + 1]
    return cut.rstrip(",;:") + "."


def intro_text(date):
    d = datetime.strptime(date, "%Y-%m-%d")
    return (f"Welcome to the Kuldeep CivilSphere daily news bulletin for {d.strftime('%A, %d %B %Y')}. "
            "These are today's top stories for U P S C preparation, grouped by General Studies paper.")


OUTRO = "That was today's bulletin from Kuldeep CivilSphere. Revise the full notes on the website, and verify facts from the original sources. Thank you for listening."


# ------------------------------------------------------------------ story selection and English scripts
def candidates(conn, date, limit=90):
    """Top mapped, non-noise stories for the day (falls back to the latest day that has news). Ordered by relevance."""
    def run(lo, hi):
        return conn.execute(
            """SELECT e.id, e.headline, e.relevance_score, p.code paper, t.name topic
               FROM news_events e JOIN event_topic_mappings m ON m.event_id=e.id AND m.is_primary=1
               JOIN syllabus_topics t ON t.id=m.topic_id JOIN syllabus_papers p ON p.id=t.paper_id
               WHERE e.event_date>=? AND e.event_date<=? AND e.merged_into IS NULL AND e.status!='rejected' AND e.noise=0
               ORDER BY e.relevance_score DESC, e.id DESC LIMIT ?""", (lo, hi, limit)).fetchall()
    d = datetime.strptime(date, "%Y-%m-%d")
    rows = run((d - timedelta(days=1)).strftime("%Y-%m-%d"), date)
    if not rows:
        last = conn.execute("SELECT MAX(event_date) FROM news_events WHERE event_date<=? AND merged_into IS NULL AND noise=0", (date,)).fetchone()[0]
        if last:
            rows = run((datetime.strptime(last, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d"), last)
    return rows


def source_text(conn, event_id, headline):
    note = conn.execute("SELECT summary, key_points FROM ai_notes WHERE event_id=?", (event_id,)).fetchone()
    parts = [headline]
    if note and note["summary"]:
        parts.append(note["summary"])
    elif note and note["key_points"]:
        try:
            parts.extend(json.loads(note["key_points"])[:4])
        except (ValueError, TypeError):
            pass
    else:
        for r in conn.execute("SELECT snippet FROM source_items WHERE event_id=? AND snippet IS NOT NULL LIMIT 2", (event_id,)):
            parts.append(r["snippet"])
    return re.sub(r"\s+", " ", " ".join(str(x) for x in parts)).replace("**", "")[:1100]


def script_prompt(batch):
    items = json.dumps([{"id": b["id"], "headline": b["headline"], "text": b["text"]} for b in batch], ensure_ascii=False)
    return ("You write a spoken radio news bulletin for UPSC civil-services aspirants in India.\n"
            "For EACH story below write ONE spoken script in plain English.\n"
            f"Length: about {ITEM_WORDS} words (30 seconds). Only if the story is exceptionally important you may use up to {MAX_WORDS} words, never more.\n"
            "Rules: use ONLY facts, names, numbers and dates present in the story text; do not invent anything. Short sentences, easy to listen to. "
            "No bullets, no symbols, no markdown, no brackets, no URLs. Spell out abbreviations only if they are not commonly spoken (say GDP, RBI, ISRO as usual). "
            "Start directly with the news, no greeting. Last sentence: why it matters for UPSC, in under 15 words, only if clear from the text.\n"
            'Return JSON exactly like {"items":[{"id":1,"script":"..."}]} with one entry per story id.\n'
            "STORIES:\n" + items)


def parse_scripts(text):
    try:
        data = json.loads(text)
    except ValueError:
        m = re.search(r"\{.*\}", text or "", re.S)
        data = json.loads(m.group(0)) if m else {}
    out = {}
    for it in (data.get("items") or []):
        try:
            out[int(it["id"])] = cap_words(str(it.get("script", "")))
        except (KeyError, ValueError, TypeError):
            continue
    return out


def fallback_script(text):
    return cap_words(text, ITEM_WORDS)


def build_english(conn, date, progress=None):
    """Create (or reuse) the English script list for the date. Stops when the estimated length reaches ~30 minutes."""
    have = conn.execute("SELECT COUNT(*) FROM bulletin_scripts WHERE bdate=?", (date,)).fetchone()[0]
    if have:
        return have
    cands = candidates(conn, date)
    if not cands:
        raise RuntimeError("No UPSC-relevant news for this date yet. Fetch news first.")
    overhead = est_seconds(intro_text(date)) + est_seconds(OUTRO) + sum(est_seconds(v) for v in LEADS.values()) + 4
    budget = TARGET_S - overhead
    chosen, total, i = [], 0.0, 0
    while i < len(cands) and total < budget - 20:
        batch = []
        for c in cands[i:i + BATCH]:
            batch.append({"id": c["id"], "headline": c["headline"], "text": source_text(conn, c["id"], c["headline"]), "paper": c["paper"]})
        i += BATCH
        scripts = {}
        if ai.enabled():
            try:
                txt, _, _ = ai.call_api(script_prompt(batch), max_tokens=2200)
                scripts = parse_scripts(txt)
            except Exception as ex:  # noqa: BLE001
                if any(k in str(ex) for k in ("429", "401", "403", "not configured")) and not chosen:
                    raise
            time.sleep(1.5)
        for b in batch:
            s = scripts.get(b["id"]) or fallback_script(b["text"])
            if words(s) < 12:
                continue
            sec = est_seconds(s)
            if total + sec > budget + 15:
                continue
            chosen.append({**b, "script": s, "sec": sec})
            total += sec
        if progress:
            progress(f"Writing scripts ({len(chosen)} stories, ~{int(total // 60)} min)")
    # play in GS order; inside each paper keep relevance order
    order = {"GS1": 1, "GS2": 2, "GS3": 3, "GS4": 4}
    chosen.sort(key=lambda b: order.get(b["paper"], 9))
    pos = 0
    conn.execute("DELETE FROM bulletin_scripts WHERE bdate=?", (date,))

    def put(kind, event_id, headline, paper, text):
        nonlocal pos
        conn.execute("INSERT INTO bulletin_scripts(bdate,pos,kind,event_id,headline,paper,en_text) VALUES(?,?,?,?,?,?,?)",
                     (date, pos, kind, event_id, headline, paper, text))
        pos += 1
    put("intro", None, "Introduction", None, intro_text(date))
    last = None
    for b in chosen:
        if b["paper"] != last:
            put("lead", None, LEADS.get(b["paper"], b["paper"]).split(".")[0], b["paper"], LEADS.get(b["paper"], ""))
            last = b["paper"]
        put("item", b["id"], b["headline"], b["paper"], b["script"])
    put("outro", None, "Closing", None, OUTRO)
    conn.commit()
    return pos


# ------------------------------------------------------------------ translation
def translate_prompt(batch, lang):
    en, native, _, _ = LANGS[lang]
    items = json.dumps([{"k": b["pos"], "text": b["en_text"]} for b in batch], ensure_ascii=False)
    return (f"Translate each text into {en} ({native}) for a spoken radio news bulletin. Write in the {en} script only (no English letters except unavoidable "
            "acronyms such as UPSC, GDP, RBI, ISRO). Use natural, simple, spoken newsreader language, not literal word-by-word translation. "
            "Keep names, numbers and dates exact. No markdown, no brackets.\n"
            'Return JSON exactly like {"items":[{"k":0,"text":"..."}]} with one entry for every k.\n'
            "TEXTS:\n" + items)


def translate_all(rows, lang, progress=None):
    """rows: list of dict(pos,en_text). Returns {pos: translated text}."""
    out = {}
    for i in range(0, len(rows), BATCH):
        batch = rows[i:i + BATCH]
        for attempt in range(2):
            try:
                txt, _, _ = ai.call_api(translate_prompt(batch, lang), max_tokens=3500)
                try:
                    data = json.loads(txt)
                except ValueError:
                    m = re.search(r"\{.*\}", txt or "", re.S)
                    data = json.loads(m.group(0)) if m else {}
                for it in data.get("items", []):
                    t = re.sub(r"\s+", " ", str(it.get("text", ""))).strip()
                    if t and int(it["k"]) in {b["pos"] for b in batch}:
                        out[int(it["k"])] = t
                if all(b["pos"] in out for b in batch):
                    break
            except Exception as ex:  # noqa: BLE001
                if any(k in str(ex) for k in ("401", "403", "not configured")):
                    raise
            time.sleep(2)
        time.sleep(1.5)
        if progress:
            progress(f"Translating to {LANGS[lang][0]} ({min(i + BATCH, len(rows))}/{len(rows)})")
    return out


# ------------------------------------------------------------------ speech
def _tts_edge(text, voice, path):
    import edge_tts

    async def go():
        await edge_tts.Communicate(text, voice, rate="+0%").save(path)
    asyncio.run(go())


def _tts_gtts(text, code, path):
    from gtts import gTTS
    gTTS(text=text, lang=code).save(path)


def tts(text, lang, path):
    """Write an MP3. Tries the neural voice first, then gTTS. Raises if both fail."""
    _, _, voice, g = LANGS[lang]
    err = None
    if voice:
        for attempt in range(2):
            try:
                _tts_edge(text, voice, path)
                if os.path.getsize(path) > 500:
                    return
            except Exception as ex:  # noqa: BLE001
                err = ex
                time.sleep(2)
    try:
        _tts_gtts(text, g, path)
        if os.path.getsize(path) > 500:
            return
    except Exception as ex:  # noqa: BLE001
        err = err or ex
    raise RuntimeError(f"Voice service failed ({type(err).__name__ if err else 'empty audio'}). Check your internet connection.")


def duration(path):
    try:
        from mutagen.mp3 import MP3
        return float(MP3(path).info.length)
    except Exception:  # noqa: BLE001
        return os.path.getsize(path) / 6000.0   # ~48 kbps fallback


def audio_dir(date, lang):
    p = Path(config.AUDIO_DIR) / date / lang
    p.mkdir(parents=True, exist_ok=True)
    return p


def cleanup_old(conn):
    cutoff = (datetime.now() - timedelta(days=config.AUDIO_KEEP_DAYS)).strftime("%Y-%m-%d")
    root = Path(config.AUDIO_DIR)
    if root.exists():
        for d in root.iterdir():
            if d.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", d.name) and d.name < cutoff:
                shutil.rmtree(d, ignore_errors=True)
    for t in ("bulletin_audio", "bulletins"):
        conn.execute(f"DELETE FROM {t} WHERE bdate<?", (cutoff,))
    conn.execute("DELETE FROM bulletin_scripts WHERE bdate<?", (cutoff,))
    conn.commit()


# ------------------------------------------------------------------ build
def build(conn, date, lang, progress=None):
    """Full build for one language. Returns (ok, message)."""
    if lang not in LANGS:
        return False, "Unknown language."
    prog = progress or (lambda m: None)
    try:
        conn.execute("INSERT OR REPLACE INTO bulletins(bdate,lang,status,created_at) VALUES(?,?, 'building', ?)", (date, lang, now_iso()))
        conn.commit()
        cleanup_old(conn)
        prog("Choosing stories and writing English scripts")
        build_english(conn, date, prog)
        rows = [dict(r) for r in conn.execute("SELECT pos,kind,event_id,headline,en_text FROM bulletin_scripts WHERE bdate=? ORDER BY pos", (date,))]
        if lang == "en":
            texts = {r["pos"]: r["en_text"] for r in rows}
        else:
            if not ai.enabled():
                raise RuntimeError("AI key needed to translate. Add GROQ_API_KEY to .env and restart.")
            texts = translate_all(rows, lang, prog)
        conn.execute("DELETE FROM bulletin_audio WHERE bdate=? AND lang=?", (date, lang))
        d = audio_dir(date, lang)
        for old in d.glob("*.mp3"):
            old.unlink()
        total, n_ok, skipped = 0.0, 0, 0
        for r in rows:
            t = texts.get(r["pos"])
            if not t:
                skipped += 1
                continue
            f = d / f"{r['pos']:03d}.mp3"
            prog(f"Recording {n_ok + 1}/{len(rows)} in {LANGS[lang][0]}")
            tts(t, lang, str(f))
            sec = duration(str(f))
            conn.execute("INSERT INTO bulletin_audio(bdate,lang,pos,kind,event_id,headline,text,seconds,file) VALUES(?,?,?,?,?,?,?,?,?)",
                         (date, lang, r["pos"], r["kind"], r["event_id"], r["headline"], t, sec, f.name))
            conn.commit()
            total += sec
            n_ok += 1
        if not n_ok:
            raise RuntimeError("No audio was produced.")
        conn.execute("UPDATE bulletins SET status='ready', total_seconds=?, created_at=?, error=? WHERE bdate=? AND lang=?",
                     (total, now_iso(), f"{skipped} item(s) skipped (translation failed)" if skipped else None, date, lang))
        conn.commit()
        return True, f"Bulletin ready: {n_ok} clips, {int(total // 60)} min {int(total % 60)} s."
    except Exception as ex:  # noqa: BLE001
        msg = f"{type(ex).__name__}: {str(ex)[:200]}"
        conn.execute("UPDATE bulletins SET status='failed', error=? WHERE bdate=? AND lang=?", (msg, date, lang))
        conn.commit()
        return False, msg


def start_background(date, lang):
    """Run build() in a thread. Returns False when this bulletin is already being built."""
    key = (date, lang)
    with _LOCK:
        if STATUS.get(key, {}).get("running"):
            return False
        STATUS[key] = {"running": True, "phase": "Starting", "error": "", "ok": None}

    def work():
        from . import db
        try:
            with db.session() as c:
                ok, msg = build(c, date, lang, lambda m: STATUS[key].update(phase=m))
            STATUS[key].update(ok=ok, phase=msg, error="" if ok else msg)
        except Exception as ex:  # noqa: BLE001
            STATUS[key].update(ok=False, error=f"{type(ex).__name__}: {str(ex)[:200]}")
        finally:
            STATUS[key]["running"] = False
    threading.Thread(target=work, daemon=True).start()
    return True


def load(conn, date, lang):
    b = conn.execute("SELECT * FROM bulletins WHERE bdate=? AND lang=?", (date, lang)).fetchone()
    clips, t = [], 0.0
    for r in conn.execute("SELECT * FROM bulletin_audio WHERE bdate=? AND lang=? ORDER BY pos", (date, lang)):
        d = dict(r)
        d["start"] = t
        t += r["seconds"]
        clips.append(d)
    return b, clips


def fmt(sec):
    sec = int(round(sec))
    return f"{sec // 60}:{sec % 60:02d}"
