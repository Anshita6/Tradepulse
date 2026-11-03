import csv
import hashlib
import hmac
import io
import re
import secrets
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .services.api_service import get_live_price, get_prices

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "casanova.db"  # kept so your orders are not lost
FEE_RATE = 0.001
SESSION_DAYS = 30
FAILS = {}

app = FastAPI(title="TradePulse")


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


# ---------- portfolio ----------
class OrderIn(BaseModel):
    symbol: str = Field(pattern=r"^[A-Za-z0-9.\-]{1,12}$")
    asset_type: Literal["crypto", "stock"]
    side: Literal["BUY", "SELL"]
    qty: float = Field(gt=0)
    price: float | None = Field(default=None, gt=0)


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
    with db() as con:
        rows = con.execute(
            "select * from orders where symbol=? and user_id=? order by id",
            (sym, user["id"]),
        ).fetchall()
    held = positions(rows).get(sym, {"qty": 0.0})["qty"]
    if o.side == "SELL" and o.qty > held + 1e-12:
        raise HTTPException(
            400, f"You hold {held:g} {sym}; you can't sell {o.qty:g}."
        )
    px = o.price or await get_live_price(sym, o.asset_type)
    if not px:
        raise HTTPException(
            502, f"No live price for {sym}. Check the symbol or enter a price."
        )
    fee = round(o.qty * px * FEE_RATE, 2)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
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
            "select * from orders where user_id=? order by id desc",
            (user["id"],),
        )
        return [dict(r) for r in rows]


@app.get("/api/orders.csv")
def orders_csv(user=Depends(current_user)):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        ["id", "time_utc", "symbol", "type", "side", "qty", "price", "fee"]
    )
    for o in list_orders(user):
        w.writerow([
            o["id"], o["ts"], o["symbol"], o["asset_type"],
            o["side"], o["qty"], o["price"], o["fee"],
        ])
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=orders.csv"},
    )


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
            "select * from orders where user_id=? order by id", (user["id"],)
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
    prev = None
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


app.mount(
    "/", StaticFiles(directory=ROOT / "frontend", html=True), name="frontend"
)