import csv
import hashlib
import hmac
import io
import os
import re
import secrets
import smtplib
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Literal

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .services.api_service import CRYPTO_MAP, get_live_price, get_prices

ROOT = Path(__file__).resolve().parents[2]
# CHANGED: DB location can be set with the TP_DB_PATH environment variable
# (useful if you attach a persistent disk on Render). Defaults to the old path.
DB_PATH = Path(os.getenv("TP_DB_PATH") or (ROOT / "casanova.db"))
FEE_RATE = 0.001
SESSION_DAYS = 30
FMT = "%Y-%m-%d %H:%M:%S"
FAILS = {}
CODE_REQS = {}

# Optional delivery settings (see the notes after the code)
SMTP_HOST = os.getenv("TP_SMTP_HOST")
SMTP_USER = os.getenv("TP_SMTP_USER")
SMTP_PASS = os.getenv("TP_SMTP_PASS")
SMTP_FROM = os.getenv("TP_SMTP_FROM") or SMTP_USER
SMTP_PORT = int(os.getenv("TP_SMTP_PORT", "587"))
TW_SID = os.getenv("TWILIO_SID")
TW_TOKEN = os.getenv("TWILIO_TOKEN")
TW_FROM = os.getenv("TWILIO_FROM")

app = FastAPI(title="TradePulse")

# ADDED: CORS, so the Netlify site is allowed to call this API.
# No trailing slashes. Extra origins can be added with the TP_ALLOWED_ORIGINS
# environment variable (comma separated).
ALLOWED_ORIGINS = [
    "https://anshita-tradepulse-5f4763.netlify.app",
    "https://tradepulse-r2hj.onrender.com",
    "http://127.0.0.1:5500",   # VS Code Live Server
    "http://localhost:5500",
    "http://127.0.0.1:8000",
    "http://localhost:8000",
]
ALLOWED_ORIGINS += [
    o.strip().rstrip("/")
    for o in os.getenv("TP_ALLOWED_ORIGINS", "").split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],  # includes the Authorization header used for login
)


def db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


with db() as _c:
    _c.execute(
        """create table if not exists orders(
        id integer primary key autoincrement,
        ts text not null,
        symbol text not null,
        asset_type text not null,
        side text not null,
        qty real not null,
        price real not null,
        fee real not null)"""
    )
    try:
        _c.execute("alter table orders add column user_id integer")
    except sqlite3.OperationalError:
        pass
    _c.execute(
        """create table if not exists users(
        id integer primary key autoincrement,
        name text not null,
        ident text not null unique,
        salt text not null,
        pw_hash text not null)"""
    )
    _c.execute(
        """create table if not exists sessions(
        token text primary key,
        user_id integer not null,
        expires real not null)"""
    )
    _c.execute(
        """create table if not exists snapshots2(
        user_id integer not null,
        day text not null,
        value real not null,
        primary key(user_id, day))"""
    )
    _c.execute(
        """create table if not exists codes(
        ident text not null,
        purpose text not null,
        code_hash text not null,
        expires real not null,
        attempts integer not null default 0,
        primary key(ident, purpose))"""
    )
    _c.execute(
        """create table if not exists watchlist(
        id integer primary key autoincrement,
        user_id integer not null,
        symbol text not null,
        asset_type text not null,
        direction text,
        target real,
        triggered integer not null default 0,
        unique(user_id, symbol, asset_type))"""
    )


# ADDED: simple health check (handy for Render and for waking the server up)
@app.get("/api/health")
def health():
    return {"status": "ok"}


# ---------- accounts ----------
class RegisterIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    identifier: str = Field(max_length=120)
    password: str = Field(min_length=8, max_length=100)


class LoginIn(BaseModel):
    identifier: str = Field(max_length=120)
    password: str = Field(max_length=100)


def norm_ident(raw: str) -> str:
    raw = raw.strip()
    if "@" in raw:
        email = raw.lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            raise HTTPException(400, "Enter a valid email address.")
        return email
    phone = re.sub(r"[\s\-()]", "", raw)
    if not re.fullmatch(r"\+?\d{7,15}", phone):
        raise HTTPException(
            400,
            "Enter a valid email, or a phone number with country code "
            "(for example +919876543210).",
        )
    return phone


def hash_pw(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), 200_000
    ).hex()


def new_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    expires = time.time() + SESSION_DAYS * 86400
    with db() as con:
        con.execute(
            "insert into sessions(token, user_id, expires) values(?,?,?)",
            (token, user_id, expires),
        )
    return token


def current_user(authorization: str = Header(default="")):
    token = authorization.removeprefix("Bearer ").strip()
    with db() as con:
        row = con.execute(
            "select u.id, u.name, u.ident from sessions s "
            "join users u on u.id = s.user_id "
            "where s.token=? and s.expires>?",
            (token, time.time()),
        ).fetchone()
    if not row:
        raise HTTPException(401, "Please sign in.")
    return row


@app.post("/api/register")
def register(b: RegisterIn):
    ident = norm_ident(b.identifier)
    salt = secrets.token_hex(16)
    with db() as con:
        if con.execute(
            "select 1 from users where ident=?", (ident,)
        ).fetchone():
            raise HTTPException(409, "An account with this email or phone exists.")
        first = con.execute("select count(*) from users").fetchone()[0] == 0
        cur = con.execute(
            "insert into users(name, ident, salt, pw_hash) values(?,?,?,?)",
            (b.name.strip(), ident, salt, hash_pw(b.password, salt)),
        )
        uid = cur.lastrowid
        if first:  # adopt orders made before accounts existed
            con.execute(
                "update orders set user_id=? where user_id is null", (uid,)
            )
    return {"token": new_session(uid), "name": b.name.strip()}


@app.post("/api/login")
def login(b: LoginIn):
    ident = norm_ident(b.identifier)
    now = time.time()
    recent = [t for t in FAILS.get(ident, []) if now - t < 300]
    FAILS[ident] = recent
    if len(recent) >= 5:
        raise HTTPException(429, "Too many attempts. Try again in a few minutes.")
    with db() as con:
        u = con.execute("select * from users where ident=?", (ident,)).fetchone()
    ok = u is not None and hmac.compare_digest(
        hash_pw(b.password, u["salt"]), u["pw_hash"]
    )
    if not ok:
        FAILS[ident].append(now)
        raise HTTPException(401, "Wrong email, phone or password.")
    FAILS[ident] = []
    return {"token": new_session(u["id"]), "name": u["name"]}


@app.post("/api/logout")
def logout(authorization: str = Header(default="")):
    token = authorization.removeprefix("Bearer ").strip()
    with db() as con:
        con.execute("delete from sessions where token=?", (token,))
    return {"ok": True}


# ---------- one-time codes (password reset and code sign-in) ----------
class CodeReq(BaseModel):
    identifier: str = Field(max_length=120)
    purpose: Literal["reset", "login"]


class CodeLogin(BaseModel):
    identifier: str = Field(max_length=120)
    code: str = Field(pattern=r"^\d{6}$")


class CodeReset(BaseModel):
    identifier: str = Field(max_length=120)
    code: str = Field(pattern=r"^\d{6}$")
    new_password: str = Field(min_length=8, max_length=100)


def channel_for(ident: str) -> str:
    if "@" in ident:
        return "email" if (SMTP_HOST and SMTP_USER and SMTP_PASS) else "console"
    return "sms" if (TW_SID and TW_TOKEN and TW_FROM) else "console"


def deliver(ident: str, code: str, purpose: str) -> None:
    text = f"Your TradePulse code is {code}. It expires in 10 minutes."
    ch = channel_for(ident)
    try:
        if ch == "email":
            msg = EmailMessage()
            msg["Subject"] = "Your TradePulse code"
            msg["From"] = SMTP_FROM
            msg["To"] = ident
            msg.set_content(text)
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as s:
                s.starttls()
                s.login(SMTP_USER, SMTP_PASS)
                s.send_message(msg)
        elif ch == "sms":
            url = (
                "https://api.twilio.com/2010-04-01/Accounts/"
                f"{TW_SID}/Messages.json"
            )
            r = httpx.post(
                url,
                auth=(TW_SID, TW_TOKEN),
                data={"To": ident, "From": TW_FROM, "Body": text},
                timeout=15,
            )
            r.raise_for_status()
        else:
            print(f"\n[TradePulse] {purpose} code for {ident}: {code}\n",
                  flush=True)
    except Exception as e:
        print(f"[TradePulse] could not send code: {e}", flush=True)


def code_hash(ident: str, purpose: str, code: str) -> str:
    return hashlib.sha256(f"{ident}|{purpose}|{code}".encode()).hexdigest()


def issue_code(ident: str, purpose: str) -> str:
    now = time.time()
    key = (ident, purpose)
    recent = [t for t in CODE_REQS.get(key, []) if now - t < 600]
    if len(recent) >= 3:
        raise HTTPException(429, "Too many codes requested. Try again in 10 minutes.")
    recent.append(now)
    CODE_REQS[key] = recent
    code = f"{secrets.randbelow(10**6):06d}"
    with db() as con:
        con.execute(
            "insert or replace into codes(ident,purpose,code_hash,expires,attempts) "
            "values(?,?,?,?,0)",
            (ident, purpose, code_hash(ident, purpose, code), now + 600),
        )
    return code


def check_code(ident: str, purpose: str, code: str) -> bool:
    with db() as con:
        row = con.execute(
            "select * from codes where ident=? and purpose=?", (ident, purpose)
        ).fetchone()
        if not row or row["expires"] < time.time() or row["attempts"] >= 5:
            return False
        con.execute(
            "update codes set attempts=attempts+1 where ident=? and purpose=?",
            (ident, purpose),
        )
        if not hmac.compare_digest(
            row["code_hash"], code_hash(ident, purpose, code)
        ):
            return False
        con.execute(
            "delete from codes where ident=? and purpose=?", (ident, purpose)
        )
    return True


@app.post("/api/code/request")
def code_request(b: CodeReq):
    ident = norm_ident(b.identifier)
    with db() as con:
        exists = con.execute(
            "select 1 from users where ident=?", (ident,)
        ).fetchone()
    code = issue_code(ident, b.purpose)
    if exists:  # same answer either way, so accounts can't be probed
        deliver(ident, code, b.purpose)
    return {"ok": True, "channel": channel_for(ident)}


@app.post("/api/code/login")
def code_login(b: CodeLogin):
    ident = norm_ident(b.identifier)
    if not check_code(ident, "login", b.code):
        raise HTTPException(401, "That code is wrong or has expired.")
    with db() as con:
        u = con.execute("select * from users where ident=?", (ident,)).fetchone()
    if not u:
        raise HTTPException(401, "That code is wrong or has expired.")
    return {"token": new_session(u["id"]), "name": u["name"]}


@app.post("/api/code/reset")
def code_reset(b: CodeReset):
    ident = norm_ident(b.identifier)
    if not check_code(ident, "reset", b.code):
        raise HTTPException(401, "That code is wrong or has expired.")
    salt = secrets.token_hex(16)
    with db() as con:
        u = con.execute("select id from users where ident=?", (ident,)).fetchone()
        if not u:
            raise HTTPException(401, "That code is wrong or has expired.")
        con.execute(
            "update users set salt=?, pw_hash=? where id=?",
            (salt, hash_pw(b.new_password, salt), u["id"]),
        )
        con.execute("delete from sessions where user_id=?", (u["id"],))
    FAILS[ident] = []
    return {"ok": True}


# ---------- orders ----------
class OrderIn(BaseModel):
    symbol: str = Field(pattern=r"^[A-Za-z0-9.\-]{1,12}$")
    asset_type: Literal["crypto", "stock"]
    side: Literal["BUY", "SELL"]
    qty: float = Field(gt=0)
    price: float | None = Field(default=None, gt=0)
    date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


def positions(rows) -> dict[str, dict]:
    pos: dict[str, dict] = {}
    for o in rows:  # rows must be oldest first
        if o["symbol"] not in pos:
            pos[o["symbol"]] = {
                "type": o["asset_type"],
                "qty": 0.0,
                "cost": 0.0,
                "realized": 0.0,
            }
        p = pos[o["symbol"]]
        if o["side"] == "BUY":
            p["qty"] += o["qty"]
            p["cost"] += o["qty"] * o["price"]
        else:
            avg = p["cost"] / p["qty"] if p["qty"] else 0.0
            p["qty"] -= o["qty"]
            p["cost"] -= avg * o["qty"]
            p["realized"] += (o["price"] - avg) * o["qty"]
    return pos


def order_ts(date_str):
    """Returns (timestamp, is_past). Raises ValueError for bad dates."""
    now = datetime.now(timezone.utc)
    if not date_str:
        return now.strftime(FMT), False
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError("use the date format YYYY-MM-DD")
    today = now.date()
    if d > today + timedelta(days=1):
        raise ValueError("the date can't be in the future")
    if d >= today:
        return now.strftime(FMT), False
    return f"{d.isoformat()} 12:00:00", True


def ledger_ok(rows):
    """None if no holding ever goes negative, else (symbol, ts)."""
    held = {}
    ordered = sorted(rows, key=lambda r: (r["ts"], r.get("id", 10**12)))
    for o in ordered:
        delta = o["qty"] if o["side"] == "BUY" else -o["qty"]
        q = held.get(o["symbol"], 0.0) + delta
        if q < -1e-9:
            return o["symbol"], o["ts"]
        held[o["symbol"]] = q
    return None


def analyze(out, total):
    """Pulse Score (0-100) and plain-English insights."""
    if not out or total <= 0:
        return 0, "No data", ["Place your first order to see your Pulse."]
    score = 100
    tips = []
    top = out[0]
    share = top["value"] / total * 100
    if share > 70:
        score -= 30
        tips.append(
            f"{top['symbol']} is {share:.0f}% of your portfolio. "
            "That is a lot riding on one asset."
        )
    elif share > 50:
        score -= 15
        tips.append(
            f"{top['symbol']} is {share:.0f}% of your portfolio. "
            "Consider balancing it."
        )
    else:
        tips.append(
            f"Your largest position, {top['symbol']}, is {share:.0f}% "
            "of the total. Nicely spread."
        )
    if len(out) == 1:
        score -= 15
        tips.append("You hold one asset. Spreading across several lowers risk.")
    elif len(out) == 2:
        score -= 5
    crypto = sum(h["value"] for h in out if h["type"] == "crypto")
    cpct = crypto / total * 100
    tips.append(f"Split: {cpct:.0f}% crypto, {100 - cpct:.0f}% stocks.")
    if cpct > 80:
        score -= 10
        tips.append("Crypto is very volatile. A stock holding can cushion swings.")
    if len(out) > 1:
        best = max(out, key=lambda h: h["pnl_pct"])
        worst = min(out, key=lambda h: h["pnl_pct"])
        tips.append(
            f"Best performer: {best['symbol']} ({best['pnl_pct']:+.1f}%). "
            f"Weakest: {worst['symbol']} ({worst['pnl_pct']:+.1f}%)."
        )
    if any(not h["live"] for h in out):
        score -= 5
        tips.append("Some live prices are unavailable, so values may be stale.")
    score = max(0, score)
    label = "Strong" if score >= 75 else "Balanced" if score >= 50 else "Risky"
    return score, label, tips


@app.get("/api/price/{asset_type}/{symbol}")
async def price(asset_type: Literal["crypto", "stock"], symbol: str):
    live = await get_live_price(symbol, asset_type)
    return {"symbol": symbol.upper(), "price": live}


@app.post("/api/orders")
async def create_order(o: OrderIn, user=Depends(current_user)):
    sym = o.symbol.upper()
    try:
        ts, past = order_ts(o.date)
    except ValueError as e:
        raise HTTPException(400, f"Trade date: {e}.")
    if past and not o.price:
        raise HTTPException(400, "Enter the price you paid for a past trade.")
    px = o.price or await get_live_price(sym, o.asset_type)
    if not px:
        raise HTTPException(
            502, f"No live price for {sym}. Check the symbol or enter a price."
        )
    with db() as con:
        rows = [dict(r) for r in con.execute(
            "select * from orders where symbol=? and user_id=?",
            (sym, user["id"]),
        )]
    rows.append({"ts": ts, "symbol": sym, "side": o.side, "qty": o.qty})
    if ledger_ok(rows):
        when = f" on {o.date}" if past else ""
        raise HTTPException(
            400, f"You don't hold enough {sym} to sell {o.qty:g}{when}."
        )
    fee = round(o.qty * px * FEE_RATE, 2)
    with db() as con:
        cur = con.execute(
            "insert into orders(ts,symbol,asset_type,side,qty,price,fee,user_id) "
            "values(?,?,?,?,?,?,?,?)",
            (ts, sym, o.asset_type, o.side, o.qty, px, fee, user["id"]),
        )
    return {"id": cur.lastrowid, "symbol": sym, "price": px, "fee": fee}


@app.get("/api/orders")
def list_orders(user=Depends(current_user)):
    with db() as con:
        rows = con.execute(
            "select * from orders where user_id=? order by ts desc, id desc",
            (user["id"],),
        )
        return [dict(r) for r in rows]


@app.get("/api/orders.csv")
def orders_csv(user=Depends(current_user)):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["date", "symbol", "type", "side", "qty", "price", "fee"])
    for o in list_orders(user):
        w.writerow([
            o["ts"][:10], o["symbol"], o["asset_type"],
            o["side"], o["qty"], o["price"], o["fee"],
        ])
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=orders.csv"},
    )


# ---------- CSV import ----------
class ImportIn(BaseModel):
    csv_text: str = Field(max_length=500_000)


HEAD = {
    "date": ("date", "time_utc", "time", "timestamp"),
    "symbol": ("symbol", "ticker", "asset"),
    "type": ("type", "asset_type"),
    "side": ("side",),
    "qty": ("qty", "quantity", "amount"),
    "price": ("price", "execution price"),
}


def pick(row: dict, key: str) -> str:
    for name in HEAD[key]:
        if row.get(name):
            return row[name]
    return ""


def parse_row(row: dict) -> dict:
    sym = pick(row, "symbol").upper()
    if not re.fullmatch(r"[A-Z0-9.\-]{1,12}", sym):
        raise ValueError("missing or invalid symbol")
    default_kind = "crypto" if sym in CRYPTO_MAP else "stock"
    kind = pick(row, "type").lower() or default_kind
    if kind not in ("crypto", "stock"):
        raise ValueError("type must be crypto or stock")
    side = pick(row, "side").upper()
    if side not in ("BUY", "SELL"):
        raise ValueError("side must be BUY or SELL")
    try:
        qty = float(pick(row, "qty").replace(",", ""))
        px = float(pick(row, "price").replace("$", "").replace(",", ""))
    except ValueError:
        raise ValueError("qty and price must be numbers")
    if qty <= 0 or px <= 0:
        raise ValueError("qty and price must be above zero")
    date = pick(row, "date")[:10]
    if not date:
        raise ValueError("missing date")
    ts, _ = order_ts(date)
    return {"ts": ts, "symbol": sym, "asset_type": kind,
            "side": side, "qty": qty, "price": px}


@app.post("/api/import")
def import_orders(b: ImportIn, user=Depends(current_user)):
    reader = csv.DictReader(io.StringIO(b.csv_text.lstrip("\ufeff")))
    if not reader.fieldnames:
        raise HTTPException(400, "The file is empty.")
    new = []
    errors = []
    for n, raw in enumerate(reader, start=2):
        if n > 2001:
            errors.append("Too many rows (the limit is 2000).")
            break
        row = {(k or "").strip().lower(): (v or "").strip()
               for k, v in raw.items()}
        try:
            new.append(parse_row(row))
        except ValueError as e:
            errors.append(f"Row {n}: {e}.")
    if errors:
        more = " ..." if len(errors) > 5 else ""
        raise HTTPException(
            400, "Nothing was imported. " + " ".join(errors[:5]) + more
        )
    if not new:
        raise HTTPException(400, "No rows found in the file.")
    with db() as con:
        old = [dict(r) for r in con.execute(
            "select * from orders where user_id=?", (user["id"],)
        )]
    seen = {(r["ts"][:10], r["symbol"], r["side"],
             round(r["qty"], 8), round(r["price"], 8)) for r in old}
    fresh = []
    for r in new:
        key = (r["ts"][:10], r["symbol"], r["side"],
               round(r["qty"], 8), round(r["price"], 8))
        if key not in seen:
            seen.add(key)
            fresh.append(r)
    bad = ledger_ok(old + fresh)
    if bad:
        raise HTTPException(
            400,
            f"Nothing was imported. The file sells more {bad[0]} than you "
            f"own around {bad[1][:10]}.",
        )
    with db() as con:
        con.executemany(
            "insert into orders(ts,symbol,asset_type,side,qty,price,fee,user_id) "
            "values(?,?,?,?,?,?,?,?)",
            [(r["ts"], r["symbol"], r["asset_type"], r["side"], r["qty"],
              r["price"], round(r["qty"] * r["price"] * FEE_RATE, 2),
              user["id"]) for r in fresh],
        )
    return {"imported": len(fresh), "skipped": len(new) - len(fresh)}


# ---------- watchlist and alerts ----------
class WatchIn(BaseModel):
    symbol: str = Field(pattern=r"^[A-Za-z0-9.\-]{1,12}$")
    asset_type: Literal["crypto", "stock"]
    direction: Literal["above", "below"] | None = None
    target: float | None = Field(default=None, gt=0)


@app.post("/api/watchlist")
def watch_add(w: WatchIn, user=Depends(current_user)):
    if (w.direction is None) != (w.target is None):
        raise HTTPException(
            400, "Choose both an alert direction and a target price, or neither."
        )
    sym = w.symbol.upper()
    with db() as con:
        count = con.execute(
            "select count(*) from watchlist where user_id=?", (user["id"],)
        ).fetchone()[0]
        exists = con.execute(
            "select 1 from watchlist where user_id=? and symbol=? "
            "and asset_type=?", (user["id"], sym, w.asset_type),
        ).fetchone()
        if count >= 30 and not exists:
            raise HTTPException(400, "Your watchlist is full (30 assets).")
        con.execute(
            "insert into watchlist(user_id,symbol,asset_type,direction,target,"
            "triggered) values(?,?,?,?,?,0) "
            "on conflict(user_id,symbol,asset_type) do update set "
            "direction=excluded.direction, target=excluded.target, triggered=0",
            (user["id"], sym, w.asset_type, w.direction, w.target),
        )
    return {"ok": True}


@app.get("/api/watchlist")
async def watch_list(user=Depends(current_user)):
    with db() as con:
        rows = [dict(r) for r in con.execute(
            "select * from watchlist where user_id=? order by id",
            (user["id"],),
        )]
    prices = await get_prices([(r["symbol"], r["asset_type"]) for r in rows])
    out = []
    fire = []
    for r in rows:
        px = prices.get(r["symbol"])
        trig = bool(r["triggered"])
        if px and r["direction"] and not trig:
            if r["direction"] == "above":
                hit = px >= r["target"]
            else:
                hit = px <= r["target"]
            if hit:
                trig = True
                fire.append((r["id"],))
        out.append({
            "id": r["id"], "symbol": r["symbol"], "type": r["asset_type"],
            "price": px, "direction": r["direction"], "target": r["target"],
            "triggered": trig,
        })
    if fire:
        with db() as con:
            con.executemany(
                "update watchlist set triggered=1 where id=?", fire
            )
    return out


@app.post("/api/watchlist/{item_id}/clear")
def watch_clear(item_id: int, user=Depends(current_user)):
    with db() as con:
        con.execute(
            "update watchlist set direction=null, target=null, triggered=0 "
            "where id=? and user_id=?", (item_id, user["id"]),
        )
    return {"ok": True}


@app.delete("/api/watchlist/{item_id}")
def watch_delete(item_id: int, user=Depends(current_user)):
    with db() as con:
        con.execute(
            "delete from watchlist where id=? and user_id=?",
            (item_id, user["id"]),
        )
    return {"ok": True}


# ---------- portfolio ----------
@app.get("/api/history")
def history(user=Depends(current_user)):
    with db() as con:
        rows = con.execute(
            "select day, value from snapshots2 where user_id=? order by day",
            (user["id"],),
        )
        return [dict(r) for r in rows]


@app.get("/api/holdings")
async def holdings(user=Depends(current_user)):
    with db() as con:
        rows = con.execute(
            "select * from orders where user_id=? order by ts, id",
            (user["id"],),
        ).fetchall()
    pos = positions(rows)
    realized = sum(p["realized"] for p in pos.values())
    open_pos = {s: p for s, p in pos.items() if p["qty"] > 1e-12}
    prices = await get_prices([(s, p["type"]) for s, p in open_pos.items()])
    out = []
    total_value = 0.0
    total_cost = 0.0
    for s, p in open_pos.items():
        avg = p["cost"] / p["qty"]
        live = prices.get(s)
        value = p["qty"] * (live if live else avg)
        total_value += value
        total_cost += p["cost"]
        pnl_pct = (value / p["cost"] - 1) * 100 if p["cost"] else 0
        out.append({
            "symbol": s,
            "type": p["type"],
            "qty": p["qty"],
            "avg_cost": avg,
            "price": live,
            "value": value,
            "pnl": value - p["cost"],
            "pnl_pct": pnl_pct,
            "live": live is not None,
        })
    out.sort(key=lambda x: -x["value"])
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with db() as con:
        row = con.execute(
            "select value from snapshots2 where user_id=? and day<? "
            "order by day desc limit 1",
            (user["id"], day),
        ).fetchone()
        prev = row["value"] if row else None
        if total_value > 0:
            con.execute(
                "insert into snapshots2(user_id, day, value) values(?,?,?) "
                "on conflict(user_id, day) do update set value=excluded.value",
                (user["id"], day, total_value),
            )
    score, label, tips = analyze(out, total_value)
    return {
        "name": user["name"],
        "holdings": out,
        "total_value": total_value,
        "total_cost": total_cost,
        "unrealized": total_value - total_cost,
        "realized": realized,
        "prev_value": prev,
        "pulse": {"score": score, "label": label, "insights": tips},
    }


# CHANGED: only mount the frontend if the folder exists, so the API still
# starts even if the frontend folder is missing. This must stay LAST.
FRONTEND_DIR = ROOT / "frontend"
if FRONTEND_DIR.is_dir():
    app.mount(
        "/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend"
    )