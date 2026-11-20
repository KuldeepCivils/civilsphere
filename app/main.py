import hashlib
import os
from pathlib import Path
import re
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
import threading
import time
from fastapi.templating import Jinja2Templates
from itsdangerous import URLSafeTimedSerializer, BadSignature

from . import config, db, ingest, briefs, seed, icons, ai, analytics, pyq as pyqmod, quiz as quizmod, bulletin as bulletinmod

from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(_app):
    seed.seed_all()
    seed.sync_keywords_background()
    threading.Timer(20, ai.start_background, args=(config.AI_AUTO_MAX,)).start()  # catch up on notes shortly after start
    stop = threading.Event()
    if config.FETCH_EVERY_MIN > 0:
        threading.Thread(target=_scheduler, args=(stop,), daemon=True).start()
    yield
    stop.set()


def _scheduler(stop):
    """Background refresh: every few minutes fetch active sources whose own interval has elapsed."""
    while not stop.wait(max(60, config.FETCH_EVERY_MIN * 60)):
        try:
            with db.session() as c:
                due = ingest.due_sources(c)
                t0 = time.time()
                for s, (items, err) in ingest.fetch_many(due):
                    ingest.record_result(c, s, items, err, t0, kind="scheduled")
            ai.start_background(config.AI_AUTO_MAX)
        except Exception:  # noqa: BLE001 - never let the scheduler thread die
            pass


app = FastAPI(title="Kuldeep CivilSphere", docs_url=None, redoc_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(config.BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(config.BASE_DIR / "templates"))
from .richtext import rich as _rich


templates.env.filters["rich"] = _rich
templates.env.globals["icon"] = icons.icon
templates.env.globals["icon_key"] = icons.icon_key
templates.env.globals["ai_enabled"] = ai.enabled
templates.env.globals["ai_status"] = lambda: ai.STATUS
templates.env.globals["ai_last"] = ai.last_run
templates.env.globals["ai_provider"] = lambda: (ai.provider() or "none").capitalize()
APP_VERSION = "0.32"
templates.env.globals["APP_VERSION"] = APP_VERSION
COOKIE = "hub_admin"
LOGIN_FAILS = {}  # ip -> (count, window_start)




def _local_tz():
    try:
        return ZoneInfo(config.TIMEZONE)
    except Exception:
        return timezone(timedelta(hours=5, minutes=30), "IST")


def today():
    return datetime.now(_local_tz()).strftime("%Y-%m-%d")


# ---------------- auth (enforced server-side) ----------------
def _ser():
    return URLSafeTimedSerializer(config.SESSION_SECRET, salt="admin-session")


def admin_enabled():
    return bool(config.ADMIN_PASSWORD and len(config.SESSION_SECRET) >= 16)


def is_admin(request: Request):
    if not admin_enabled():
        return False
    tok = request.cookies.get(COOKIE)
    if not tok:
        return False
    try:
        return _ser().loads(tok, max_age=8 * 3600).get("admin") is True
    except BadSignature:
        return False


def csrf_for(request: Request):
    tok = request.cookies.get(COOKIE, "")
    return hmac.new(config.SESSION_SECRET.encode() or b"x", tok.encode(), hashlib.sha256).hexdigest()


def require_admin(request: Request):
    if not is_admin(request):
        raise HTTPException(status_code=303, headers={"Location": "/login"})


def require_post(request: Request, csrf: str):
    require_admin(request)
    if not hmac.compare_digest(csrf or "", csrf_for(request)):
        raise HTTPException(status_code=403, detail="Bad CSRF token")


def feed_health():
    """Meaningful status dot: reflects real source/job state only."""
    try:
        with db.session() as c:
            live = c.execute("SELECT COUNT(*) FROM sources WHERE active=1 AND verification='working'").fetchone()[0]
            last = c.execute("SELECT status FROM fetch_jobs ORDER BY id DESC LIMIT 1").fetchone()
        if last and last["status"] == "failed":
            return {"level": "bad", "label": "Last fetch failed", "detail": "The most recent news fetch failed. Open Admin for details."}
        if live:
            return {"level": "ok", "label": f"{live} feed(s) live", "detail": f"{live} news source(s) active and tested."}
        return {"level": "mid", "label": "No live feeds", "detail": "No source is active yet. An admin can press Quick start."}
    except Exception:  # never break a page because of the status dot
        return {"level": "mid", "label": "Status unknown", "detail": "Could not read feed status."}


def render(request, name, **ctx):
    vid, fresh, act, sid_in = None, False, None, request.cookies.get("hub_sid")
    try:  # visitor counter must never break a page
        with db.session() as c:
            vid_in = request.cookies.get("hub_vid")
            if request.method == "GET":
                vid, fresh = analytics.touch(c, vid_in, has_session=bool(sid_in))
            else:
                vid = vid_in
            act = analytics.stats(c, vid)
    except Exception:
        act = None
    ctx.update(activity=act, is_admin=is_admin(request), csrf=csrf_for(request) if is_admin(request) else "",
               today=today(), tz=config.TIMEZONE, path=request.url.path, health=feed_health())
    resp = templates.TemplateResponse(request, name, ctx)
    if fresh and vid:
        resp.set_cookie("hub_vid", vid, max_age=365 * 24 * 3600, httponly=True, samesite="lax", secure=config.COOKIE_SECURE)
    if vid and request.method == "GET" and not sid_in:  # session cookie (no expiry): ends when the browser is closed
        resp.set_cookie("hub_sid", secrets.token_hex(8), httponly=True, samesite="lax", secure=config.COOKIE_SECURE)
    return resp


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return render(request, "login.html", enabled=admin_enabled(), error=None)


@app.post("/login")
def login(request: Request, password: str = Form("")):
    ip = request.client.host if request.client else "?"
    cnt, start = LOGIN_FAILS.get(ip, (0, datetime.now()))
    if datetime.now() - start > timedelta(minutes=10):
        cnt, start = 0, datetime.now()
    if cnt >= 5:
        return render(request, "login.html", enabled=admin_enabled(), error="Too many attempts. Try again later.")
    if admin_enabled() and hmac.compare_digest(password.encode(), config.ADMIN_PASSWORD.encode()):
        resp = RedirectResponse("/admin", status_code=303)
        resp.set_cookie(COOKIE, _ser().dumps({"admin": True}), httponly=True, samesite="strict", max_age=8 * 3600, secure=config.COOKIE_SECURE)
        LOGIN_FAILS.pop(ip, None)
        return resp
    LOGIN_FAILS[ip] = (cnt + 1, start)
    return render(request, "login.html", enabled=admin_enabled(), error="Invalid credentials or admin not configured.")


@app.post("/logout")
def logout():
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie(COOKIE)
    return resp


# ---------------- public pages ----------------
@app.get("/health")
def health():
    with db.session() as c:
        c.execute("SELECT 1").fetchone()
    return JSONResponse({"status": "ok"})


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    with db.session() as c:
        d = today()
        total_events = c.execute("SELECT COUNT(*) FROM news_events WHERE merged_into IS NULL AND status!='rejected'").fetchone()[0]
        today_events = c.execute("SELECT COUNT(*) FROM news_events WHERE event_date=? AND merged_into IS NULL AND status!='rejected'", (d,)).fetchone()[0]
        top = c.execute(
            """SELECT e.id, e.headline, e.relevance_score, e.data_origin, p.code paper, t.name topic
               FROM news_events e LEFT JOIN event_topic_mappings m ON m.event_id=e.id AND m.is_primary=1
               LEFT JOIN syllabus_topics t ON t.id=m.topic_id LEFT JOIN syllabus_papers p ON p.id=t.paper_id
               WHERE e.merged_into IS NULL AND e.status!='rejected' ORDER BY e.event_date DESC, e.relevance_score DESC LIMIT 8""").fetchall()
        coverage = {}
        for days in (7, 30, 90):
            since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
            rows = c.execute(
                """SELECT p.code, COUNT(*) n FROM news_events e
                   JOIN event_topic_mappings m ON m.event_id=e.id AND m.is_primary=1
                   JOIN syllabus_topics t ON t.id=m.topic_id JOIN syllabus_papers p ON p.id=t.paper_id
                   WHERE e.event_date>=? AND e.merged_into IS NULL AND e.status!='rejected' GROUP BY p.code""", (since,)).fetchall()
            coverage[days] = {r["code"]: r["n"] for r in rows}
        quiet = c.execute(
            """SELECT p.code, t.name, (SELECT COUNT(*) FROM event_topic_mappings m JOIN news_events e ON e.id=m.event_id
                  WHERE m.topic_id=t.id AND e.event_date>=date('now','-30 day') AND e.merged_into IS NULL) n
               FROM syllabus_topics t JOIN syllabus_papers p ON p.id=t.paper_id ORDER BY n, p.sort_order LIMIT 8""").fetchall()
        srcs = c.execute("SELECT verification, active, COUNT(*) n FROM sources WHERE access_method='rss' GROUP BY verification, active").fetchall()
        review = c.execute("SELECT COUNT(*) FROM news_events WHERE needs_review=1 AND status='auto' AND merged_into IS NULL").fetchone()[0]
        last_job = c.execute("SELECT * FROM fetch_jobs ORDER BY id DESC LIMIT 1").fetchone()
        brief = c.execute("SELECT r.id, r.period_start FROM reports r WHERE kind='daily' ORDER BY period_start DESC LIMIT 1").fetchone()
        days14 = []
        counts = {r["event_date"]: r["n"] for r in c.execute(
            """SELECT event_date, COUNT(*) n FROM news_events WHERE event_date>=date('now','-14 day') AND merged_into IS NULL
               AND status!='rejected' AND noise=0 GROUP BY event_date""")}
        for i in range(13, -1, -1):
            dd = datetime.now(_local_tz()) - timedelta(days=i)
            days14.append({"d": dd.strftime("%Y-%m-%d"), "label": dd.strftime("%d %b"), "wd": dd.strftime("%a"), "n": counts.get(dd.strftime("%Y-%m-%d"), 0)})
        heat = c.execute(
            """SELECT p.code, t.id, t.name, (SELECT COUNT(*) FROM event_topic_mappings m JOIN news_events e ON e.id=m.event_id
                  WHERE m.topic_id=t.id AND e.event_date>=date('now','-30 day') AND e.merged_into IS NULL AND e.status!='rejected' AND e.noise=0) n
               FROM syllabus_topics t JOIN syllabus_papers p ON p.id=t.paper_id ORDER BY p.sort_order, t.sort_order""").fetchall()
        notes_n = c.execute("SELECT COUNT(*) FROM ai_notes").fetchone()[0]
        quiz_n = c.execute("SELECT COUNT(*) FROM quiz_questions k JOIN quizzes q ON q.id=k.quiz_id WHERE q.quiz_date=?", (d,)).fetchone()[0]
        top_ai = {r[0] for r in c.execute("SELECT event_id FROM ai_notes")}
    # --- v0.32 home: 30-day trend chart, week-on-week change, per-paper syllabus coverage, today's reading list
    with db.session() as c:
        counts30 = {r["event_date"]: r["n"] for r in c.execute(
            """SELECT event_date, COUNT(*) n FROM news_events WHERE event_date>=date('now','-31 day') AND merged_into IS NULL
               AND status!='rejected' AND noise=0 GROUP BY event_date""")}
        wk = lambda a, b: c.execute("""SELECT COUNT(*) FROM news_events WHERE event_date>date('now',?) AND event_date<=date('now',?)
               AND merged_into IS NULL AND status!='rejected' AND noise=0""", (a, b)).fetchone()[0]
        week_new, prev_week = wk("-7 day", "+1 day"), wk("-14 day", "-7 day")
        last_day = c.execute("SELECT MAX(event_date) FROM news_events WHERE event_date<=? AND merged_into IS NULL AND noise=0", (d,)).fetchone()[0]
        read_ids = [r[0] for r in c.execute("""SELECT id FROM news_events WHERE event_date=? AND relevance_score>=50 AND merged_into IS NULL
               AND status!='rejected' AND noise=0""", (last_day,))] if last_day else []
    pts = []
    for i in range(29, -1, -1):
        dd = datetime.now(_local_tz()) - timedelta(days=i)
        pts.append((dd.strftime("%d %b"), counts30.get(dd.strftime("%Y-%m-%d"), 0)))
    mx = max([n for _, n in pts] + [1])
    top_y = max(5, ((mx + 4) // 5) * 5)
    W, H, L, B = 440, 190, 34, 24
    xs = [L + i * (W - L - 10) / 29 for i in range(30)]
    ys = [H - B - (n / top_y) * (H - B - 12) for _, n in pts]
    line = " ".join(("M" if i == 0 else "L") + f"{x:.1f} {y:.1f}" for i, (x, y) in enumerate(zip(xs, ys)))
    trend = {"line": line, "area": line + f" L{xs[-1]:.1f} {H - B} L{xs[0]:.1f} {H - B} Z", "W": W, "H": H, "L": L, "B": B,
             "last": {"x": xs[-1], "y": ys[-1], "n": pts[-1][1], "total": sum(n for _, n in pts)},
             "xt": [(xs[i], pts[i][0]) for i in (0, 7, 14, 21, 29)],
             "yt": [(H - B - (v / top_y) * (H - B - 12), v) for v in sorted({0, top_y // 4, top_y // 2, 3 * top_y // 4, top_y})]}
    week_pct = round((week_new - prev_week) / prev_week * 100) if prev_week else None
    paper_cov = {}
    for code in ("GS1", "GS2", "GS3", "GS4"):
        tp = [h for h in heat if h["code"] == code]
        paper_cov[code] = {"touched": sum(1 for h in tp if h["n"] > 0), "total": len(tp)}
    hour = datetime.now(_local_tz()).hour
    greeting = "Good morning" if hour < 12 else "Good afternoon" if hour < 17 else "Good evening"
    return render(request, "dashboard.html", total_events=total_events, today_events=today_events, top=top, top_ai=top_ai,
                  coverage=coverage, quiet=quiet, srcs=srcs, review=review, last_job=last_job, brief=brief,
                  days14=days14, heat=heat, notes_n=notes_n, quiz_n=quiz_n, greeting=greeting,
                  cos12=[__import__('math').cos(i*__import__('math').pi/6) for i in range(12)], sin12=[__import__('math').sin(i*__import__('math').pi/6) for i in range(12)],
                  trend=trend, week_new=week_new, week_pct=week_pct, paper_cov=paper_cov, read_ids=read_ids)


@app.get("/news", response_class=HTMLResponse)
def news(request: Request, paper: str = "", date: str = "", min_score: float = 0, q: str = "", view: str = "cards", all: int = 0):
    with db.session() as c:
        sections, n = briefs.collect_events(c, date=date or None, paper=paper, min_score=min_score, q=q, limit=200, show_all=bool(all))
        total = c.execute("SELECT COUNT(*) FROM news_events WHERE merged_into IS NULL AND status!='rejected'").fetchone()[0]
        notes_n = c.execute("SELECT COUNT(*) FROM ai_notes").fetchone()[0]
        papers = c.execute("SELECT code, name FROM syllabus_papers ORDER BY sort_order").fetchall()
    return render(request, "news.html", sections=sections, n=n, papers=papers, view="table" if view == "table" else "cards",
                  f={"paper": paper, "date": date, "min_score": min_score, "q": q}, show_all=bool(all), hidden=max(0, total - n) if not all else 0, notes_n=notes_n)


@app.get("/paper/{code}", response_class=HTMLResponse)
def gs_paper_page(request: Request, code: str, days: int = 30):
    days = days if days in (1, 7, 30, 90, 365) else 30
    with db.session() as c:
        p = c.execute("SELECT * FROM syllabus_papers WHERE code=?", (code.upper(),)).fetchone()
        if not p:
            raise HTTPException(404)
        since = (datetime.now(_local_tz()) - timedelta(days=days)).strftime("%Y-%m-%d")
        sections, n = briefs.collect_events(c, paper=p["code"], since=since, limit=200)
        topics = c.execute(
            """SELECT t.id, t.name, (SELECT COUNT(*) FROM event_topic_mappings m JOIN news_events e ON e.id=m.event_id
                 WHERE m.topic_id=t.id AND e.merged_into IS NULL AND e.status!='rejected' AND e.noise=0 AND e.event_date>=?) n
               FROM syllabus_topics t WHERE paper_id=? ORDER BY sort_order""", (since, p["id"])).fetchall()
    return render(request, "paper.html", paper=p, topics=topics, sections=sections, n=n, days=days)


@app.get("/topic/{tid}", response_class=HTMLResponse)
def topic_page(request: Request, tid: int):
    with db.session() as c:
        t = c.execute("SELECT t.*, p.code paper, p.name paper_name FROM syllabus_topics t JOIN syllabus_papers p ON p.id=t.paper_id WHERE t.id=?", (tid,)).fetchone()
        if not t:
            raise HTTPException(404)
        sections, n = briefs.collect_for_topic(c, tid)
    return render(request, "topic.html", topic=t, sections=sections, n=n)


@app.get("/event/{eid}", response_class=HTMLResponse)
def event_page(request: Request, eid: int):
    with db.session() as c:
        e = c.execute("SELECT * FROM news_events WHERE id=?", (eid,)).fetchone()
        if not e:
            raise HTTPException(404)
        if e["merged_into"]:
            return RedirectResponse(f"/event/{e['merged_into']}", status_code=302)
        srcs = c.execute(
            """SELECT si.*, s.name publisher, s.category, s.content_rights FROM source_items si
               JOIN sources s ON s.id=si.source_id WHERE si.event_id=? ORDER BY si.published_at""", (eid,)).fetchall()
        maps = c.execute(
            """SELECT m.*, t.name topic, t.official_wording, p.code paper, p.name paper_name
               FROM event_topic_mappings m JOIN syllabus_topics t ON t.id=m.topic_id JOIN syllabus_papers p ON p.id=t.paper_id
               WHERE m.event_id=? ORDER BY m.is_primary DESC, m.confidence DESC""", (eid,)).fetchall()
        import json
        bd = json.loads(e["score_breakdown"]) if e["score_breakdown"] else None
        others = c.execute("SELECT id, headline FROM news_events WHERE merged_into IS NULL AND id!=? ORDER BY id DESC LIMIT 50", (eid,)).fetchall() if is_admin(request) else []
        sections = briefs.event_card(c, eid)
    return render(request, "event.html", e=e, srcs=srcs, maps=maps, bd=bd, others=others, sections=sections, msg=request.query_params.get("msg"))


@app.get("/quiz", response_class=HTMLResponse)
def quiz_page(request: Request, date: str = ""):
    try:
        d = datetime.strptime(date, "%Y-%m-%d").strftime("%Y-%m-%d") if date else today()
    except ValueError:
        raise HTTPException(404)
    with db.session() as c:
        qz, qs = quizmod.load_quiz(c, d)
        fallback = False
        if not qz:
            qs = quizmod.pyq_fallback(c, d)
            fallback = bool(qs)
        past = c.execute("SELECT q.quiz_date, COUNT(k.id) n FROM quizzes q JOIN quiz_questions k ON k.quiz_id=q.id GROUP BY q.id ORDER BY q.quiz_date DESC LIMIT 30").fetchall()
    return render(request, "quiz.html", qz=qz, qs=qs, qdate=d, past=past, fallback=fallback, msg=request.query_params.get("msg"))


@app.get("/mock", response_class=HTMLResponse)
def mock_paper_page(request: Request, days: int = 7, n: int = 25, src: str = "news", subject: str = "", y0: int = 1995, y1: int = 2026):
    with db.session() as c:
        if src == "pyq":  # a paper made only of past-year Prelims questions
            n = max(5, min(n, 100))
            picked = pyqmod.sample_prelims(c, n, subject[:60], y0, y1, seed=str(time.time()))
            qs = [{"id": -p["id"], "kind": "pyq", "question": p["question"], "options": p["options"], "answer_idx": p["answer_idx"],
                   "explanation": p["explanation"] or "", "headline": None, "quiz_date": None, "pyq_tag": p["tag"], "subject": p["subject"], "topic": p["topic"]} for p in picked]
            mains = []
        else:
            qs = quizmod.paper_questions(c, days, n)
            mains = quizmod.paper_mains(c, days)
        subs = pyqmod.subjects(c)
    return render(request, "mockpaper.html", qs=qs, mains=mains, subs=subs, src=src, subject=subject, y0=y0, y1=y1, days=max(1, min(days, 60)), n=n, minutes=round(len(qs) * 1.2), marks=len(qs) * 2)


@app.get("/pyq", response_class=HTMLResponse)
def pyq_browse(request: Request, subject: str = "", year: int = 0, q: str = "", page: int = 1):
    page = max(1, min(page, 500))
    with db.session() as c:
        total, rows = pyqmod.browse(c, subject[:60], year, q[:80], (page - 1) * 20, 20)
        subs = pyqmod.subjects(c)
    return render(request, "pyqbrowse.html", rows=rows, total=total, subs=subs, f={"subject": subject, "year": year, "q": q}, page=page,
                  pages=max(1, -(-total // 20)), years=list(range(2026, 1994, -1)))


@app.get("/admin/pyq", response_class=HTMLResponse)
def pyq_admin(request: Request):
    require_admin(request)
    with db.session() as c:
        rows = c.execute("SELECT * FROM pyq ORDER BY year DESC, exam, id DESC LIMIT 300").fetchall()
    return render(request, "pyq.html", rows=[pyqmod._row(r) for r in rows], msg=request.query_params.get("msg"))


@app.post("/admin/pyq")
def pyq_import(request: Request, csrf: str = Form(""), text: str = Form("")):
    require_post(request, csrf)
    entries, errors = pyqmod.parse_paste(text[:200000])
    with db.session() as c:
        added = sum(pyqmod.add(c, e) for e in entries)
        db.audit(c, "pyq_import", f"{added} added, {len(errors)} problems")
    msg = f"{added} question(s) added." + (" Problems: " + " | ".join(errors[:4]) if errors else "")
    return _back("/admin/pyq", msg)


@app.post("/admin/quiz/generate")
def quiz_generate(request: Request, csrf: str = Form(""), date: str = Form("")):
    require_post(request, csrf)
    try:
        d = datetime.strptime(date, "%Y-%m-%d").strftime("%Y-%m-%d") if date else today()
    except ValueError:
        return _back("/quiz", "Invalid date.")
    with db.session() as c:
        ok, msg = quizmod.generate_quiz(c, d)
        db.audit(c, "quiz_generate", f"{d}: {msg}")
    return _back("/quiz", msg) if not ok else RedirectResponse(f"/quiz?date={d}", status_code=303)


# ---------------------------------------------------------------- audio news bulletin
def _can_build_audio(request: Request):
    """Admin, or someone using the app on this same computer (same-origin request)."""
    if is_admin(request):
        return True
    host = request.client.host if request.client else ""
    if host not in ("127.0.0.1", "::1", "testclient"):
        return False
    origin = request.headers.get("origin") or request.headers.get("referer") or ""
    return (not origin) or (request.headers.get("host", "") in origin)


def _audio_date(date):
    try:
        return datetime.strptime(date, "%Y-%m-%d").strftime("%Y-%m-%d") if date else today()
    except ValueError:
        raise HTTPException(404)


@app.get("/audio", response_class=HTMLResponse)
def audio_page(request: Request, date: str = "", lang: str = "en"):
    d = _audio_date(date)
    if lang not in bulletinmod.LANGS:
        lang = "en"
    with db.session() as c:
        b, clips = bulletinmod.load(c, d, lang)
        ready = {r["lang"] for r in c.execute("SELECT lang FROM bulletins WHERE bdate=? AND status='ready'", (d,))}
        days = [r[0] for r in c.execute("SELECT DISTINCT bdate FROM bulletins WHERE status='ready' ORDER BY bdate DESC LIMIT 7")]
    st = bulletinmod.STATUS.get((d, lang), {})
    total = sum(x["seconds"] for x in clips)
    return render(request, "audio.html", d=d, lang=lang, langs=bulletinmod.LANGS, b=b, clips=clips, ready=ready, days=days, total=total,
                  fmt=bulletinmod.fmt, running=bool(st.get("running")), can_build=_can_build_audio(request),
                  csrf_tok=csrf_for(request) if is_admin(request) else "", msg=request.query_params.get("msg"),
                  n_items=sum(1 for x in clips if x["kind"] == "item"))


@app.post("/audio/generate")
def audio_generate(request: Request, lang: str = Form("en"), date: str = Form(""), csrf: str = Form("")):
    if not _can_build_audio(request):
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    if is_admin(request) and not hmac.compare_digest(csrf or "", csrf_for(request)):
        raise HTTPException(status_code=403)
    d = _audio_date(date)
    if lang not in bulletinmod.LANGS:
        lang = "en"
    if os.environ.get("UPSC_NO_AUTO"):
        return RedirectResponse(f"/audio?date={d}&lang={lang}&msg=Background+jobs+are+off", status_code=303)
    bulletinmod.start_background(d, lang)
    return RedirectResponse(f"/audio?date={d}&lang={lang}", status_code=303)


@app.get("/audio/status")
def audio_status(date: str = "", lang: str = "en"):
    d = _audio_date(date)
    st = bulletinmod.STATUS.get((d, lang), {})
    with db.session() as c:
        b = c.execute("SELECT status, error FROM bulletins WHERE bdate=? AND lang=?", (d, lang)).fetchone()
    return JSONResponse({"running": bool(st.get("running")), "phase": st.get("phase", ""), "error": st.get("error", ""),
                         "status": b["status"] if b else "none"})


def _clip_dir(d, lang):
    if lang not in bulletinmod.LANGS or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
        raise HTTPException(404)
    return Path(config.AUDIO_DIR) / d / lang


@app.get("/audio/clip/{d}/{lang}/{name}")
def audio_clip(d: str, lang: str, name: str):
    if not re.fullmatch(r"\d{3}\.mp3", name):
        raise HTTPException(404)
    f = _clip_dir(d, lang) / name
    if not f.exists():
        raise HTTPException(404)
    return FileResponse(str(f), media_type="audio/mpeg")


@app.get("/audio/full/{d}/{lang}.mp3")
def audio_full(d: str, lang: str):
    folder = _clip_dir(d, lang)
    with db.session() as c:
        names = [r["file"] for r in c.execute("SELECT file FROM bulletin_audio WHERE bdate=? AND lang=? ORDER BY pos", (d, lang))]
    files = [folder / n for n in names if (folder / n).exists()]
    if not files:
        raise HTTPException(404)

    def gen():
        for f in files:
            yield f.read_bytes()
    return StreamingResponse(gen(), media_type="audio/mpeg",
                             headers={"Content-Disposition": f'attachment; filename="CivilSphere-news-{d}-{lang}.mp3"'})


@app.get("/brief", response_class=HTMLResponse)
def brief_list(request: Request):
    with db.session() as c:
        rows = c.execute(
            """SELECT r.id, r.period_start, MAX(v.version) latest, MAX(v.generated_at) at, MAX(v.input_event_count) n
               FROM reports r JOIN report_versions v ON v.report_id=r.id WHERE r.kind='daily'
               GROUP BY r.id ORDER BY r.period_start DESC LIMIT 60""").fetchall()
    return render(request, "brief_list.html", rows=rows, msg=request.query_params.get("msg"))


@app.get("/brief/{rid}", response_class=HTMLResponse)
def brief_view(request: Request, rid: int, v: int = 0):
    with db.session() as c:
        r = c.execute("SELECT * FROM reports WHERE id=?", (rid,)).fetchone()
        if not r:
            raise HTTPException(404)
        vers = c.execute("SELECT version, status, generated_at, generator FROM report_versions WHERE report_id=? ORDER BY version DESC", (rid,)).fetchall()
        cur = c.execute("SELECT * FROM report_versions WHERE report_id=? AND version=?", (rid, v or vers[0]["version"])).fetchone()
    return render(request, "brief_view.html", r=r, versions=vers, cur=cur)


@app.get("/syllabus", response_class=HTMLResponse)
def syllabus(request: Request):
    with db.session() as c:
        papers = c.execute("SELECT * FROM syllabus_papers ORDER BY sort_order").fetchall()
    return render(request, "syllabus.html", papers=papers)


# ---------------- admin (every route checks the server-side session) ----------------
@app.get("/admin", response_class=HTMLResponse)
def admin_home(request: Request):
    require_admin(request)
    with db.session() as c:
        jobs = c.execute("SELECT j.*, s.name sname FROM fetch_jobs j LEFT JOIN sources s ON s.id=j.source_id ORDER BY j.id DESC LIMIT 30").fetchall()
        review = c.execute(
            """SELECT e.id, e.headline, e.relevance_score FROM news_events e
               WHERE e.needs_review=1 AND e.status='auto' AND e.merged_into IS NULL ORDER BY e.id DESC LIMIT 50""").fetchall()
        audit = c.execute("SELECT * FROM admin_audit_logs ORDER BY id DESC LIMIT 20").fetchall()
    return render(request, "admin.html", jobs=jobs, review=review, audit=audit, msg=request.query_params.get("msg"))


@app.get("/admin/sources", response_class=HTMLResponse)
def admin_sources(request: Request):
    require_admin(request)
    with db.session() as c:
        rows = c.execute("SELECT * FROM sources ORDER BY category, name").fetchall()
    return render(request, "sources.html", sources=rows, msg=request.query_params.get("msg"))


@app.get("/admin/import", response_class=HTMLResponse)
def import_page(request: Request):
    require_admin(request)
    with db.session() as c:
        srcs = c.execute("SELECT id, name FROM sources WHERE access_method='manual' ORDER BY name").fetchall()
        recent = c.execute("""SELECT si.title, si.url, s.name publisher, si.retrieved_at FROM source_items si JOIN sources s ON s.id=si.source_id
                              WHERE si.data_origin='manual' ORDER BY si.id DESC LIMIT 15""").fetchall()
    return render(request, "import.html", srcs=srcs, recent=recent, msg=request.query_params.get("msg"))


@app.post("/admin/import")
def import_links(request: Request, csrf: str = Form(""), source_id: int = Form(...), lines: str = Form("")):
    """Manual link import for sources with no feed (EPW, monthly magazines). One per line: Title | URL | optional own note."""
    require_post(request, csrf)
    items, bad = [], 0
    for ln in lines.splitlines()[:200]:
        if not ln.strip():
            continue
        parts = [p.strip() for p in ln.split("|")]
        if len(parts) < 2 or not parts[0] or not parts[1].lower().startswith(("http://", "https://")):
            bad += 1
            continue
        note = ("Your note: " + parts[2][:300]) if len(parts) > 2 and parts[2] else ""
        items.append({"title": parts[0][:300], "url": parts[1][:1000], "published": ingest.now_iso(), "author": None, "snippet": note})
    with db.session() as c:
        s = c.execute("SELECT * FROM sources WHERE id=? AND access_method='manual'", (source_id,)).fetchone()
        if not s:
            raise HTTPException(404)
        seen, new, rej = ingest.store_items(c, source_id, items, "manual")
        db.audit(c, "manual_import", f"{new} new of {len(items)} lines for {s['name']}")
    return _back("/admin/import", f"{new} new link(s) added, {seen - new - rej} already present." + (f" {bad + rej} line(s) skipped (use: Title | https://link | optional note)." if bad + rej else ""))


def _back(url, msg):
    from urllib.parse import quote
    return RedirectResponse(f"{url}?msg={quote(msg)}", status_code=303)


@app.post("/admin/sources/add")
def source_add(request: Request, csrf: str = Form(""), name: str = Form(...), category: str = Form(...),
               feed_url: str = Form(""), base_url: str = Form(""), notes: str = Form("")):
    require_post(request, csrf)
    if feed_url and not feed_url.lower().startswith(("http://", "https://")):
        return _back("/admin/sources", "Feed URL must start with http(s)://")
    with db.session() as c:
        try:
            c.execute("INSERT INTO sources(name,category,base_url,feed_url,access_method,access_notes,active,verification) VALUES(?,?,?,?,?,?,0,'untested')",
                      (name.strip()[:120], category.strip()[:60], base_url.strip(), feed_url.strip(), "rss" if feed_url else "manual_link", notes.strip()[:500]))
        except Exception:
            return _back("/admin/sources", "Source already exists.")
        db.audit(c, "source_add", name)
    return _back("/admin/sources", "Source added (inactive, untested). Use Test, then Activate.")


@app.post("/admin/sources/{sid}/test")
def source_test(request: Request, sid: int, csrf: str = Form("")):
    require_post(request, csrf)
    with db.session() as c:
        s = c.execute("SELECT * FROM sources WHERE id=?", (sid,)).fetchone()
        if not s:
            raise HTTPException(404)
        ok, msg, _ = ingest.test_source(s)
        c.execute("UPDATE sources SET verification=?, last_error=? WHERE id=?", ("working" if ok else "failing", None if ok else msg, sid))
        db.audit(c, "source_test", f"{s['name']}: {msg}")
    return _back("/admin/sources", f"{s['name']}: {msg}")


@app.post("/admin/sources/{sid}/toggle")
def source_toggle(request: Request, sid: int, csrf: str = Form("")):
    require_post(request, csrf)
    with db.session() as c:
        s = c.execute("SELECT * FROM sources WHERE id=?", (sid,)).fetchone()
        if not s:
            raise HTTPException(404)
        if not s["active"] and s["access_method"] != "rss":
            return _back("/admin/sources", "Cannot activate: no automated connector exists for this source.")
        c.execute("UPDATE sources SET active=1-active WHERE id=?", (sid,))
        db.audit(c, "source_toggle", s["name"])
    return _back("/admin/sources", "Updated.")


@app.post("/admin/sources/{sid}/fetch")
def source_fetch(request: Request, sid: int, csrf: str = Form("")):
    require_post(request, csrf)
    with db.session() as c:
        if not c.execute("SELECT 1 FROM sources WHERE id=?", (sid,)).fetchone():
            raise HTTPException(404)
        _, status, seen, new, err = ingest.run_fetch_job(c, sid)
        db.audit(c, "manual_fetch", f"source {sid}: {status}")
    return _back("/admin", f"Fetch {status}: {seen} seen, {new} new." + (f" Error: {err}" if err else ""))


@app.post("/admin/fetch-all")
def fetch_all(request: Request, csrf: str = Form("")):
    require_post(request, csrf)
    with db.session() as c:
        res = ingest.run_all_active(c)
        ai.start_background(config.AI_AUTO_MAX)
        db.audit(c, "fetch_all", f"{len(res)} sources")
    return _back("/admin", f"Ran {len(res)} active source(s)." if res else "No active RSS sources to run.")


@app.post("/admin/event/{eid}/reject")
def event_reject(request: Request, eid: int, csrf: str = Form("")):
    require_post(request, csrf)
    with db.session() as c:
        c.execute("UPDATE news_events SET status='rejected' WHERE id=?", (eid,))
        db.audit(c, "event_reject", str(eid))
    return _back("/admin", "Event rejected (hidden, recoverable in DB).")


@app.post("/admin/event/{eid}/approve")
def event_approve(request: Request, eid: int, csrf: str = Form("")):
    require_post(request, csrf)
    with db.session() as c:
        c.execute("UPDATE news_events SET status='reviewed', needs_review=0 WHERE id=?", (eid,))
        db.audit(c, "event_approve", str(eid))
    return _back("/admin", "Event marked reviewed.")


@app.post("/admin/event/{eid}/merge")
def event_merge(request: Request, eid: int, csrf: str = Form(""), into: int = Form(...)):
    require_post(request, csrf)
    if into == eid:
        return _back("/admin", "Cannot merge an event into itself.")
    with db.session() as c:
        if not c.execute("SELECT 1 FROM news_events WHERE id=? AND merged_into IS NULL", (into,)).fetchone():
            return _back("/admin", "Target event not found.")
        c.execute("UPDATE source_items SET event_id=? WHERE event_id=?", (into, eid))
        c.execute("UPDATE news_events SET merged_into=? WHERE id=?", (into, eid))
        c.execute("DELETE FROM event_topic_mappings WHERE event_id=?", (eid,))
        ingest.classify_event(c, into)
        db.audit(c, "event_merge", f"{eid} -> {into}")
    return _back("/admin", f"Merged event {eid} into {into}; all source links kept.")


@app.post("/admin/brief/generate")
def brief_generate(request: Request, csrf: str = Form(""), date: str = Form("")):
    require_post(request, csrf)
    try:
        datetime.strptime(date or today(), "%Y-%m-%d")
    except ValueError:
        return _back("/brief", "Invalid date.")
    with db.session() as c:
        ok, msg, rid = briefs.generate_daily(c, date or today())
        db.audit(c, "brief_generate", msg)
    return _back("/brief", msg)


@app.post("/admin/quickstart")
def quickstart(request: Request, csrf: str = Form("")):
    """Test every RSS source, activate those that work, then fetch. Reports honestly per source."""
    require_post(request, csrf)
    with db.session() as c:
        ok_names, bad, new = ingest.quickstart_run(c)
        ai.start_background(config.AI_AUTO_MAX)
        db.audit(c, "quickstart", f"{len(ok_names)} ok, {len(bad)} failed, {new} new items")
    msg = f"{len(ok_names)} source(s) working and activated, {new} new item(s) fetched."
    if bad:
        msg += f" Could not reach {len(bad)}: " + ", ".join(n for n, _ in bad[:8]) + (" ..." if len(bad) > 8 else "") + " (see Sources page for each error)."
    return _back("/admin", msg)


@app.post("/admin/ai/event/{eid}")
def ai_event(request: Request, eid: int, csrf: str = Form("")):
    require_post(request, csrf)
    with db.session() as c:
        ok, msg = ai.generate_for_event(c, eid)
        db.audit(c, "ai_notes", f"event {eid}: {msg}")
    return _back(f"/event/{eid}", msg)


@app.post("/admin/ai/test")
def ai_test(request: Request, csrf: str = Form("")):
    require_post(request, csrf)
    ok, msg = ai.test_connection()
    return _back("/admin", msg)


@app.post("/admin/ai/bulk")
def ai_bulk(request: Request, csrf: str = Form(""), date: str = Form(""), next: str = Form("/admin")):
    """Start writing notes for the top recent events in the background (it continues after this page loads)."""
    require_post(request, csrf)
    back = next if next in ("/admin", "/news", "/brief") else "/admin"
    if ai.STATUS["running"]:
        return _back(back, f"Already writing notes ({ai.STATUS['done']} of {ai.STATUS['total']} done). Refresh in a minute.")
    ai.start_background(config.AI_AUTO_MAX)
    with db.session() as c:
        db.audit(c, "ai_bulk", "background run started")
    return _back(back, "Started in the background: first gathering related coverage and reference background, then writing AI notes" + ("" if ai.enabled() else " (AI is off, so only the first step)") + ". Refresh in a minute or two.")


@app.post("/track/ping")
def track_ping(request: Request):
    """Heartbeat from the page while the user is active. Adds at most real elapsed time (capped)."""
    with db.session() as c:
        vid = request.cookies.get("hub_vid")
        analytics.ping(c, vid)
        a = analytics.stats(c, vid if vid and analytics._VID.match(vid) else None)
    return JSONResponse({k: a[k] for k in ("visitors", "visits", "pageviews", "time", "this_visit")})
