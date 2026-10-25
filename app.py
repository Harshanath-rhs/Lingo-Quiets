"""LingoQuest v2 - gamified English learning (Streamlit + Google Sheets).
Mobile-first · kid-friendly · high polish UI
"""
import base64
import hashlib
import html
import io
import random
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import gspread
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from google.oauth2.service_account import Credentials
from gspread.utils import rowcol_to_a1
from PIL import Image, ImageOps

st.set_page_config(
    page_title="LingoQuest",
    page_icon="🎮",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# ----------------------------------------------------------------- config
BASE = Path(__file__).parent
PROFILE_DIR = BASE / "profile_picture"          # username.jpeg
LEAGUE_DIR = BASE / "assets" / "leagues"        # bronze_1.ico ...
IMG_DIR = BASE / "assets" / "images"            # mascot_idle.png ...
TZ = timezone(timedelta(hours=5, minutes=30))   # Sri Lanka
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
QUEST_SIZE, TIME_LIMIT, BOARD_SIZE = 5, 30, 20
LEGEND_XP = 40000                               # XP needed to reach Legend
PRACTICE_RATE = 0.25                            # XP rate when replaying old questions
MEDALS = ["🥇", "🥈", "🥉"]
LETTERS = "ABCD"

FAMILIES = ["bronze", "silver", "gold", "crystal", "master", "champion", "titan"]
ROMAN = ["I", "II", "III"]
LEAGUES = [(f"{f}_{n + 1}", f"{f.title()} {ROMAN[n]}", f, ROMAN[n])
           for f in FAMILIES for n in range(3)] + [("legend", "Legend", "legend", "★")]
THRESH = [0] + [int(round(LEGEND_XP * (i / (len(LEAGUES) - 1)) ** 1.7 / 50) * 50)
                for i in range(1, len(LEAGUES))]

USER_COLS = ("username", "password", "display_name", "xp", "badges", "achievements",
             "streak", "last_played", "answered")
Q_COLS = ("id", "week", "question", "option_a", "option_b", "option_c", "option_d",
          "correct", "xp", "difficulty", "active")

esc = html.escape


def ui(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)


def to_int(v, default=0) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def league_of(xp: int) -> int:
    return max(i for i, t in enumerate(THRESH) if xp >= t)


# ----------------------------------------------------------------- images
@st.cache_data(show_spinner=False)
def _load(path: str, size: int, square: bool, mtime: float) -> str:
    im = Image.open(path).convert("RGBA")
    if square:
        im = ImageOps.fit(im, (size, size)).convert("RGB")
    else:
        im.thumbnail((size, size))
    buf, fmt = io.BytesIO(), ("JPEG" if square else "PNG")
    im.save(buf, fmt, **({"quality": 82} if square else {}))
    mime = "jpg" if square else "png"
    return f"data:image/{mime};base64," + base64.b64encode(buf.getvalue()).decode()


def pic(folder: Path, stem: str, size: int, exts, square=False):
    for e in exts:
        p = folder / f"{stem}{e}"
        if p.exists():
            return _load(str(p), size, square, p.stat().st_mtime)
    return None


def art(name: str, emoji: str, cls="art") -> str:
    src = pic(IMG_DIR, name, 256, (".png",))
    return (f'<img class="{cls}" src="{src}" alt="">' if src
            else f'<span class="{cls} emoji">{emoji}</span>')


def league_icon(i: int, size=64, cls="lg-ico") -> str:
    key, label, fam, num = LEAGUES[i]
    src = pic(LEAGUE_DIR, key, size, (".ico", ".png"))
    return (f'<img class="{cls}" src="{src}" alt="{label}">' if src
            else f'<span class="lg-fallback lg-{fam} {cls}">{num}</span>')


def avatar(username: str, name: str, fam: str, cls="") -> str:
    src = pic(PROFILE_DIR, username.lower(), 112, (".jpeg", ".jpg", ".png"), square=True)
    inner = f'<img src="{src}" alt="">' if src else esc((name or username)[:1].upper())
    return f'<div class="avatar lg-{fam} {cls}">{inner}</div>'


# ----------------------------------------------------------------- sound
BOOT_JS = """<script>(function(){var P=window.parent;if(!P.LQ){var ctx=null;
var ac=function(){if(!ctx){ctx=new(P.AudioContext||P.webkitAudioContext)();}
if(ctx.state==='suspended'){ctx.resume();}return ctx;};
var tone=function(f,d,t,v,w){var c=ac(),o=c.createOscillator(),g=c.createGain(),s=c.currentTime+w;
o.type=t;o.frequency.setValueAtTime(f,s);g.gain.setValueAtTime(.0001,s);
g.gain.exponentialRampToValueAtTime(v,s+.01);g.gain.exponentialRampToValueAtTime(.0001,s+d);
o.connect(g);g.connect(c.destination);o.start(s);o.stop(s+d+.05);};
var S={click:[[700,.05,'triangle',.08,0]],
start:[[392,.12,'square',.07,0],[523,.12,'square',.07,.12],[784,.22,'square',.07,.24]],
correct:[[784,.12,'triangle',.18,0],[1047,.28,'triangle',.18,.1]],
combo:[[523,.08,'triangle',.15,0],[659,.08,'triangle',.15,.08],[784,.08,'triangle',.15,.16],[1047,.25,'triangle',.15,.24]],
wrong:[[220,.25,'sawtooth',.1,0],[165,.35,'sawtooth',.1,.15]],
tick:[[880,.05,'square',.05,0]],
timeup:[[300,.2,'sawtooth',.1,0],[200,.45,'sawtooth',.1,.2]],
chest:[[600,.1,'sine',.15,0],[800,.1,'sine',.15,.1],[1000,.1,'sine',.15,.2],[1400,.35,'sine',.15,.3]],
finish:[[523,.15,'triangle',.16,0],[659,.15,'triangle',.16,.15],[784,.15,'triangle',.16,.3],[1047,.45,'triangle',.16,.45]],
levelup:[[523,.15,'square',.09,0],[659,.15,'square',.09,.15],[784,.15,'square',.09,.3],[1047,.2,'square',.09,.45],[784,.12,'square',.09,.65],[1047,.12,'square',.09,.77],[1319,.6,'square',.09,.9]]};
P.LQ={muted:false,play:function(n){if(P.LQ.muted){return;}
try{(S[n]||[]).forEach(function(x){tone(x[0],x[1],x[2],x[3],x[4]);});}catch(e){}}};
P.document.addEventListener('click',function(e){if(e.target.closest&&e.target.closest('button')){P.LQ.play('click');}},true);}
P.LQ.muted=__MUTED__;})();</script>"""

TIMER_HTML = """<style>
body{margin:0;font-family:Fredoka,sans-serif;color:#fff;text-align:center;background:transparent}
#n{font-size:28px;font-weight:700;letter-spacing:.5px;text-shadow:0 2px 8px rgba(0,0,0,.35)}
.t{height:16px;border-radius:99px;background:rgba(0,0,0,.35);overflow:hidden;border:1px solid rgba(255,255,255,.25);box-shadow:inset 0 2px 6px rgba(0,0,0,.25)}
.t i{display:block;height:100%;border-radius:99px;background:linear-gradient(90deg,#00f5d4,#7b2ff7,#ff3cac);background-size:200% 100%;animation:shine 2.5s linear infinite;transition:width 1s linear;box-shadow:0 0 12px rgba(0,245,212,.55)}
@keyframes shine{0%{background-position:0% 50%}100%{background-position:200% 50%}}
</style>
<div id="n"></div><div class="t"><i id="b"></i></div>
<script>var left=__LEFT__,total=__TOTAL__,n=document.getElementById('n'),b=document.getElementById('b'),
P=window.parent,done=false;
function draw(){var s=Math.max(0,Math.ceil(left));n.textContent='⏱ '+s;b.style.width=(Math.max(left,0)/total*100)+'%';
if(s<=10){n.style.color='#ff5d73';n.style.textShadow='0 0 12px #ff5d73';}else{n.style.color='#fff';n.style.textShadow='0 2px 8px rgba(0,0,0,.35)';}}
draw();var iv=setInterval(function(){left-=1;draw();
if(left<=5&&left>0&&P.LQ){P.LQ.play('tick');}
if(left<=0&&!done){done=true;clearInterval(iv);
var btn=P.document.querySelector('.st-key-timeout button');if(btn){btn.click();}}},1000);</script>"""


def sound_boot():
    components.html(BOOT_JS.replace("__MUTED__", "false" if st.session_state.sound else "true"), height=0)


def sfx(*names):
    st.session_state.sfxq.extend(names)


def flush_sfx():
    q = st.session_state.sfxq
    if q:
        calls = "".join(f"setTimeout(function(){{P.LQ&&P.LQ.play('{n}')}},{i * 420 + 200});"
                        for i, n in enumerate(q))
        components.html(f"<script>var P=window.parent;{calls}</script>", height=0)
        st.session_state.sfxq = []


# ----------------------------------------------------------- data layer
@st.cache_resource
def get_sheet():
    info = dict(st.secrets["gcp_service_account"])
    info["private_key"] = info["private_key"].replace("\\n", "\n").strip()
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    return gspread.authorize(creds).open_by_key(st.secrets["sheet_id"])


@st.cache_data(ttl=30, show_spinner=False)
def read_tab(name: str, cols: tuple) -> pd.DataFrame:
    rows = get_sheet().worksheet(name).get_all_records()
    return pd.DataFrame(rows).reindex(columns=list(cols)).fillna("").astype(str)


def verify(stored: str, supplied: str) -> bool:
    stored = str(stored).strip()
    if len(stored) == 64 and all(c in "0123456789abcdefABCDEF" for c in stored):
        return hashlib.sha256(supplied.encode()).hexdigest() == stored.lower()
    return stored == supplied


def authenticate(username: str, password: str):
    df = read_tab("users", USER_COLS)
    m = df[df["username"].str.lower() == username.strip().lower()]
    if m.empty or not verify(m.iloc[0]["password"], password):
        return None
    r = m.iloc[0]
    return {"username": r["username"], "name": r["display_name"] or r["username"],
            "xp": to_int(r["xp"])}


def save_results(user: dict, q: dict, gained: int) -> dict:
    ss = get_sheet()
    ws = ss.worksheet("users")
    headers = ws.row_values(1)
    col = {h: i + 1 for i, h in enumerate(headers)}
    cell = ws.find(user["username"], in_column=col["username"])
    cur = dict(zip(headers, ws.row_values(cell.row)))

    today = datetime.now(TZ).date()
    last = cur.get("last_played", "")
    try:
        last_d = datetime.strptime(last, "%Y-%m-%d").date()
    except ValueError:
        last_d = None
    streak, daily = to_int(cur.get("streak")), 0
    if last_d != today:
        streak = streak + 1 if last_d == today - timedelta(days=1) else 1
        daily = min(10 * streak, 100)
    total = to_int(cur.get("xp")) + gained + daily

    ach = {a.strip() for a in cur.get("achievements", "").split(",") if a.strip()}
    ach.add("First Quest ✅")
    if q["correct"] == len(q["qs"]):
        ach.add("Perfect Score 💯")
    if q["best"] >= 5:
        ach.add("Combo King 👑")
    if streak >= 7:
        ach.add("Week Warrior 🔥")
    if total >= 5000:
        ach.add("XP Hunter ⚡")

    answered = cur.get("answered", "")
    if not q["practice"]:
        answered = ",".join(filter(None, [answered] + [str(i) for i, _ in q["log"]]))

    values = {"xp": total, "badges": LEAGUES[league_of(total)][1],
              "achievements": ", ".join(sorted(ach)), "streak": streak,
              "last_played": today.isoformat(), "answered": answered}
    ws.batch_update([{"range": rowcol_to_a1(cell.row, col[k]), "values": [[v]]}
                     for k, v in values.items() if k in col])
    try:
        now = datetime.now(TZ).isoformat(timespec="seconds")
        ss.worksheet("progress").append_rows(
            [[user["username"], i, str(ok).upper(), now] for i, ok in q["log"]])
    except Exception:
        pass
    st.cache_data.clear()
    return {"total": total, "daily": daily, "streak": streak}


# ----------------------------------------------------------- state / nav
def init_state():
    for k, v in {"user": None, "page": "home", "quest": None, "sfxq": [], "sound": True}.items():
        st.session_state.setdefault(k, v)


def go(page): st.session_state.page = page
def toggle_sound(): st.session_state.sound = not st.session_state.sound
def logout(): st.session_state.update(user=None, page="home", quest=None)


def nav():
    with st.container(key="nav"):
        st.button("🏆 Arena", key="nav_home", on_click=go, args=("home",))
        st.button("⚔️ Quests", key="nav_quests", on_click=go, args=("quests",))
        st.button("🔊" if st.session_state.sound else "🔇", key="nav_sound", on_click=toggle_sound)
        st.button("🚪 Exit", key="nav_exit", on_click=logout)


# ---------------------------------------------------------------- login
def page_login():
    ui(f'''
    <div class="glass hero login-hero">
      {art("mascot_idle", "🦉")}
      <h1>LingoQuest</h1>
      <p class="tagline">Learn English. Earn XP. Climb the leagues.</p>
      <div class="login-sparkles">✨ 🌟 ✨</div>
    </div>
    ''')
    with st.form("login_form"):
        username = st.text_input("Username", placeholder="Enter your username")
        password = st.text_input("Password", type="password", placeholder="Enter your password")
        ok = st.form_submit_button("🚀 Start Adventure")
    if ok:
        try:
            user = authenticate(username, password)
        except Exception as e:
            st.error(f"{type(e).__name__}: {e}")
            return
        if user:
            st.session_state.user = user
            sfx("start")
            st.rerun()
        st.error("Wrong username or password. Check both and try again.")


# ----------------------------------------------------------------- home
def board_df() -> pd.DataFrame:
    df = read_tab("users", USER_COLS).copy()
    df["xp"] = df["xp"].map(to_int)
    return df.sort_values("xp", ascending=False, kind="stable").reset_index(drop=True)


def lb_row(rank: int, r, mine: bool) -> str:
    xp = int(r["xp"])
    i = league_of(xp)
    _, label, fam, _ = LEAGUES[i]
    name = r["display_name"] or r["username"]
    top = f" top top{rank}" if rank <= 3 else ""
    flames = ""
    fire = '<span class="name-fire">🔥</span>' if rank <= 3 else ""
    medal = MEDALS[rank - 1] if rank <= 3 else str(rank)
    chips = "".join(f'<span class="chip">{esc(a.strip())}</span>'
                    for a in r["achievements"].split(",") if a.strip())
    return (f'<div class="lb-row{" me" if mine else ""}{top}">{flames}<div class="rank">{medal}</div>'
            + avatar(r["username"], name, fam)
            + f'<div class="who"><b>{esc(name)}{fire}</b><div class="lg-line lg-{fam}">'
              f'{league_icon(i, 32)}<span>{label}</span></div><div class="chips">{chips}</div></div>'
              f'<div class="xp">{xp:,}<small>XP</small></div></div>')


def page_home():
    me = st.session_state.user
    df = board_df()
    hit = df.index[df["username"].str.lower() == me["username"].lower()]
    pos = int(hit[0]) if len(hit) else None
    row = df.loc[pos] if pos is not None else None
    xp = int(row["xp"]) if row is not None else me["xp"]
    li = league_of(xp)
    _, label, fam, _ = LEAGUES[li]
    nxt = li + 1 if li + 1 < len(LEAGUES) else None
    pct = 100 if nxt is None else int((xp - THRESH[li]) / (THRESH[nxt] - THRESH[li]) * 100)
    nxt_html = ('<small class="top-league">👑 Top league reached. Defend it!</small>' if nxt is None else
                f'<div class="next">{league_icon(nxt, 40, "lg-ico locked")}'
                f'<span>{THRESH[nxt] - xp:,} XP to {LEAGUES[nxt][1]}</span></div>')

    streak, today_done = (0, False)
    if row is not None:
        try:
            d = datetime.strptime(row["last_played"], "%Y-%m-%d").date()
            t = datetime.now(TZ).date()
            streak, today_done = (to_int(row["streak"]) if d >= t - timedelta(days=1) else 0), d == t
        except ValueError:
            pass
    streak_html = (f'<div class="streak">🔥 {streak}-day streak'
                   f'{"" if today_done else " · play today to keep it!"}</div>' if streak else
                   '<div class="streak">🔥 Play today to start a streak</div>')

    rival = ""
    if pos is not None and pos > 0:
        a = df.loc[pos - 1]
        rival = f'<div class="rival">🎯 {int(a["xp"]) - xp + 1:,} XP to pass {esc(a["display_name"] or a["username"])}</div>'
    elif pos == 0 and len(df) > 1:
        rival = f'<div class="rival">👑 You lead by {xp - int(df.loc[1, "xp"]):,} XP. Defend your throne!</div>'

    ui(f'''
    <div class="glass hero profile-card">
      {avatar(me["username"], me["name"], fam, "big")}
      <h2>{esc(me["name"])}</h2>
      <div class="league-badge lg-{fam}">
        {league_icon(li, 128, "lg-ico big")}
        <p class="tier">{label}</p>
      </div>
      <div class="stats">
        <div class="stat"><b>{xp:,}</b><span>XP</span></div>
        <div class="stat"><b>#{pos + 1 if pos is not None else "-"}</b><span>Rank</span></div>
        <div class="stat"><b>{len(df)}</b><span>Players</span></div>
      </div>
      <div class="bar"><i style="width:{pct}%"></i></div>
      {nxt_html}
      {streak_html}
      {rival}
    </div>
    ''')
    st.button("⚔️ Play a Quest", key="cta", on_click=go, args=("quests",))

    rows = [lb_row(i + 1, r, i == pos) for i, r in df.head(BOARD_SIZE).iterrows()]
    if pos is not None and pos >= BOARD_SIZE:
        rows += ['<div class="gap">• • •</div>', lb_row(pos + 1, row, True)]
    ui('<div class="glass lb-card"><h3>🏆 Leaderboard</h3>' + "".join(rows) + "</div>")


# ----------------------------------------------------------------- quest
def start_quest():
    me = st.session_state.user
    users = read_tab("users", USER_COLS)
    row = users[users["username"].str.lower() == me["username"].lower()].iloc[0]
    answered = {a for a in row["answered"].split(",") if a}
    qs = read_tab("questions", Q_COLS)
    active = qs[qs["active"].str.upper() == "TRUE"]
    fresh = active[~active["id"].isin(answered)]
    practice = fresh.empty and not active.empty
    pool = (active if practice else fresh).copy()
    band = 1 + league_of(to_int(row["xp"])) * 5 // len(LEAGUES)
    pool["gap"] = (pool["difficulty"].map(lambda v: to_int(v, 1)) - band).abs()
    pool["rnd"] = [random.random() for _ in range(len(pool))]
    picks = pool.sort_values(["gap", "rnd"]).head(QUEST_SIZE).sample(frac=1)
    st.session_state.quest = {"qs": picks.to_dict("records"), "i": 0, "started": time.time(),
                              "picked": None, "gained": 0, "correct": 0, "streak": 0, "best": 0,
                              "log": [], "saved": False, "practice": practice, "last": None}
    sfx("start")


def answer(letter: str):
    q = st.session_state.quest
    cur = q["qs"][q["i"]]
    elapsed = time.time() - q["started"]
    if elapsed > TIME_LIMIT + 2:
        return do_timeout()
    ok = letter == cur["correct"].strip().upper()
    q["picked"] = letter
    q["log"].append((cur["id"], ok))
    if ok:
        base = to_int(cur["xp"], 10)
        base = max(1, round(base * PRACTICE_RATE)) if q["practice"] else base
        q["streak"] += 1
        q["best"] = max(q["best"], q["streak"])
        speed = round(base * 0.5 * max(0.0, 1 - elapsed / TIME_LIMIT))
        combo = round(base * 0.1 * min(q["streak"] - 1, 4))
        q["gained"] += base + speed + combo
        q["correct"] += 1
        q["last"] = {"ok": True, "gain": base + speed + combo, "speed": speed, "combo": combo}
        sfx("combo" if q["streak"] >= 3 else "correct")
    else:
        q["streak"] = 0
        q["last"] = {"ok": False}
        sfx("wrong")


def do_timeout():
    q = st.session_state.quest
    if q and q["picked"] is None and q["i"] < len(q["qs"]):
        q["picked"] = "-"
        q["streak"] = 0
        q["log"].append((q["qs"][q["i"]]["id"], False))
        q["last"] = {"ok": False, "timeout": True}
        sfx("timeup")


def next_question():
    q = st.session_state.quest
    q["i"] += 1
    q["picked"] = None
    q["started"] = time.time()


def leave_quest():
    st.session_state.quest = None
    st.session_state.page = "home"


def finalize(q: dict):
    me = st.session_state.user
    full = len(q["qs"]) and q["correct"] == len(q["qs"]) and not q["practice"]
    q.setdefault("perfect", 50 if full else 0)
    q.setdefault("chest", 0 if q["practice"] else
                 random.choices([0, 10, 25, 50, 100], [30, 40, 20, 8, 2])[0])
    old = me["xp"]
    res = save_results(me, q, q["gained"] + q["perfect"] + q["chest"])
    me["xp"] = res["total"]
    q.update(saved=True, daily=res["daily"], days=res["streak"], old_xp=old,
             leveled=league_of(res["total"]) > league_of(old))
    sfx("finish")
    if q["chest"]:
        sfx("chest")
    if q["leveled"]:
        sfx("levelup")


def quest_intro():
    me = st.session_state.user
    li = league_of(me["xp"])
    ui(f'''
    <div class="glass hero intro-card">
      {art("mascot_idle", "🦉")}
      <h2>Ready for a Quest?</h2>
      <div class="rules">
        <div>⏱ <b>{TIME_LIMIT}s</b> per question</div>
        <div>⚡ Faster answers = bonus XP</div>
        <div>🔥 Chain correct answers for combo XP</div>
        <div>💯 Perfect round: <b>+50 XP</b></div>
        <div>🎁 Finish to open a mystery chest</div>
      </div>
      <p class="tier">{LEAGUES[li][1]}</p>
    </div>
    ''')
    st.button("⚡ Start Quest", key="start", on_click=start_quest)


def quest_result(q: dict):
    if not q["saved"]:
        try:
            finalize(q)
        except Exception as e:
            st.error(f"Couldn't save your score ({type(e).__name__}). Check your connection and retry.")
            st.button("🔁 Retry save", key="retry")
            return
    me = st.session_state.user
    li = league_of(me["xp"])
    lines = ""
    if q["perfect"]:
        lines += f'<div>💯 Perfect round +{q["perfect"]} XP</div>'
    if q["daily"]:
        lines += f'<div>📅 Daily streak bonus +{q["daily"]} XP</div>'
    if q["practice"]:
        lines += '<div>🔁 Practice round: reduced XP</div>'
    chest = ""
    if q["chest"]:
        chest = f'<div class="chest">{art("chest", "🎁", "art")}<b>+{q["chest"]} XP chest!</b></div>'
    elif not q["practice"]:
        chest = f'<div class="chest">{art("chest", "🎁", "art")}<b>Empty chest. Try again!</b></div>'

    total_xp = q["gained"] + q["perfect"] + q["chest"] + q["daily"]
    ui(f'''
    <div class="glass hero celebrate">
      {art("mascot_happy", "🎉")}
      <h2>Quest Complete!</h2>
      <div class="confetti"></div>
      <div class="stats">
        <div class="stat"><b>+{total_xp}</b><span>XP earned</span></div>
        <div class="stat"><b>{q["correct"]}/{len(q["qs"])}</b><span>Correct</span></div>
        <div class="stat"><b>{q["best"]}</b><span>Best combo</span></div>
      </div>
      <div class="bonus">{lines}</div>
      {chest}
    </div>
    ''')
    if q["leveled"]:
        _, label, fam, _ = LEAGUES[li]
        ui(f'''
        <div class="glass levelup lg-{fam}">
          <h2>🎉 LEAGUE UP!</h2>
          {league_icon(li, 128, "lg-ico big")}
          <p class="tier">{label}</p>
        </div>
        ''')
    st.button("⚡ Play Again", key="again", on_click=start_quest)
    st.button("🏆 See Leaderboard", key="finish", on_click=leave_quest)


def quest_play(q: dict):
    elapsed = time.time() - q["started"]
    if q["picked"] is None and elapsed > TIME_LIMIT + 1:
        do_timeout()
    n, cur = len(q["qs"]), q["qs"][q["i"]]
    combo = f'<span class="combo">🔥 Combo x{q["streak"]}</span>' if q["streak"] >= 2 else ""
    stars = "⭐" * max(1, min(5, to_int(cur["difficulty"], 1)))
    ui(f'''
    <div class="glass question-card">
      <div class="bar"><i style="width:{q["i"] / n * 100:.0f}%"></i></div>
      <div class="q-meta">
        <small>Question {q["i"] + 1} of {n} · {stars}{" · Practice" if q["practice"] else ""}</small>
        {combo}
      </div>
      <h2 class="question">{esc(cur["question"])}</h2>
    </div>
    ''')

    correct = cur["correct"].strip().upper()
    if q["picked"] is None:
        components.html(TIMER_HTML.replace("__LEFT__", f"{max(0.0, TIME_LIMIT - elapsed):.1f}")
                        .replace("__TOTAL__", str(TIME_LIMIT)), height=78)
        with st.container(key="opts"):
            for L in LETTERS:
                st.button(f"{L}   {cur['option_' + L.lower()]}", key=f"opt_{q['i']}_{L}",
                          on_click=answer, args=(L,))
        st.button("timeout", key="timeout", on_click=do_timeout)
        return

    opts = ""
    for L in LETTERS:
        state = "correct" if L == correct else ("wrong" if L == q["picked"] else "")
        opts += f'<div class="opt {state}"><b>{L}</b>{esc(cur["option_" + L.lower()])}</div>'
    last = q["last"] or {}
    if last.get("ok"):
        extra = "".join([f' ⚡+{last["speed"]}' if last["speed"] else "",
                         f' 🔥+{last["combo"]}' if last["combo"] else ""])
        msg, cls = f'🎉 Correct! +{last["gain"]} XP{extra}', "ok"
        confetti = '<div class="mini-confetti"></div>'
    elif last.get("timeout"):
        msg, cls = f"⏰ Time's up! Answer: {correct}", "no"
        confetti = ""
    else:
        msg, cls = f"❌ Not quite. Answer: {correct}", "no"
        confetti = ""
    ui(f'<div class="opts">{opts}</div><div class="toast {cls}">{msg}{confetti}</div>')
    st.button("🏁 Finish" if q["i"] + 1 >= n else "Next Question →", key=f"next_{q['i']}",
              on_click=next_question)


def page_quests():
    q = st.session_state.quest
    if q is None:
        return quest_intro()
    if not q["qs"]:
        ui(f'''
        <div class="glass hero">
          {art("mascot_happy", "🎉")}
          <h2>No questions available</h2>
          <p>New questions are coming soon. Check back later.</p>
        </div>
        ''')
        st.button("Back to Arena", key="empty_back", on_click=leave_quest)
        return
    if q["i"] >= len(q["qs"]):
        return quest_result(q)
    quest_play(q)


# ----------------------------------------------------------------- main
def main():
    ui(f"<style>{(BASE / 'style.css').read_text(encoding='utf-8')}</style>")
    ui('''
    <div class="bg-layer">
      <div class="stars"></div>
      <div class="orb o1"></div>
      <div class="orb o2"></div>
      <div class="orb o3"></div>
      <div class="floating-emoji e1">⭐</div>
      <div class="floating-emoji e2">✨</div>
      <div class="floating-emoji e3">🌟</div>
      <div class="floating-emoji e4">💫</div>
    </div>
    ''')
    init_state()
    sound_boot()
    if not st.session_state.user:
        page_login()
    else:
        {"home": page_home, "quests": page_quests}[st.session_state.page]()
        nav()
    flush_sfx()


main()