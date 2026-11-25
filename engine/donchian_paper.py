"""Donchian H4 paper engine (the machine-1 live bot's rule) -> docs/data/dashboard.json for the Telegram mini app.

Same rule as bot/trendmode.py of the live bot:
  entry   closed H4 candle closes above the highest high of the previous 100 H4 candles, first candle to do so
          (a flip). No new entry while that coin has an open position.
          volume filter (VOL_MULT, default 1.5, 0 = off): the breakout candle's volume must exceed VOL_MULT x the mean
          volume of the 20 H4 candles before it. Applied to breakouts closing on/after VOL_FROM (2026-11-25, the day the
          live bot got it), so the earlier paper history stays what the bot actually did.
  stop    initial = entry - 6 x ATR14(H4); afterwards highest price since entry - 6 x ATR, only ever raised.
  exit    stop touched (fill at the stop, or at the open on a gap), or 30 days (180 H4 candles).
  sizing  RISK_PCT of equity per trade, compounding; skipped when open notional would exceed CAP x equity.
  costs   0.07% per side + real funding.

Stateless: every run replays everything from PAPER_START on public Binance data, so a missed run never corrupts
anything. Trades whose entry is before DEPLOYED_AT (first run) are tagged "backfill".
No API key is needed. Telegram alerts are sent only when TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set.

    python engine/donchian_paper.py
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "data" / "dashboard.json"

SYMBOLS = os.getenv("SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,ZECUSDT,AVAXUSDT,XRPUSDT,NEARUSDT").split(",")
PAPER_START = pd.Timestamp(os.getenv("PAPER_START", "2026-01-01"), tz="UTC")
EQUITY0 = float(os.getenv("PAPER_EQUITY", "10000"))
RISK_PCT = float(os.getenv("RISK_PCT", "2"))
LOOKBACK = int(os.getenv("LOOKBACK", "100"))
K_ATR = float(os.getenv("TRAIL_ATR", "6"))
CAP = float(os.getenv("CAP", "3"))
VOL_MULT = float(os.getenv("VOL_MULT", "1.5"))
VOL_FROM = pd.Timestamp(os.getenv("VOL_FROM", "2026-11-25"), tz="UTC")
VOL_WINDOW = 20
FEE = 0.0007
MAX_BARS = 180
MIN_HISTORY = 360
H4 = pd.Timedelta(hours=4)
HOSTS = ["https://fapi.binance.com", "https://fapi1.binance.com", "https://fapi2.binance.com", "https://fapi3.binance.com"]


SPOT_HOST = "https://data-api.binance.vision"  # Binance's official public market-data endpoint (spot)
VISION = "https://data.binance.vision/data/futures/um/monthly/fundingRate"
SOURCE = {"klines": "futures", "funding": "futures"}
_FAPI_OK = os.getenv("FORCE_SPOT", "0") != "1"


def _get(path: str, params: dict, hosts=None):
    last = None
    for attempt in range(2):
        for host in hosts or HOSTS:
            try:
                r = requests.get(host + path, params=params, timeout=15)
                if r.status_code == 200 and r.text.strip():
                    return r.json()
                last = f"{host} HTTP {r.status_code}"
            except (requests.RequestException, ValueError) as exc:
                last = f"{host} {exc}"
        time.sleep(1 + attempt)
    raise RuntimeError(f"Binance request failed: {path} {last}")


def _fapi(path: str, params: dict):
    """Futures API, or None when it is not reachable from here (e.g. GitHub's US runners get HTTP 202/451)."""
    global _FAPI_OK
    if not _FAPI_OK:
        return None
    try:
        return _get(path, params)
    except RuntimeError as exc:
        print(f"[WARN] futures API unreachable, switching to public spot data: {exc}", flush=True)
        _FAPI_OK = False
        return None


def klines(sym: str, interval: str, start_ms: int) -> pd.DataFrame:
    rows, cur, now_ms = [], start_ms, int(time.time() * 1000)
    while cur < now_ms:
        batch = _fapi("/fapi/v1/klines", {"symbol": sym, "interval": interval, "startTime": cur, "limit": 1500})
        lim = 1500
        if batch is None:
            SOURCE["klines"] = "spot"
            lim = 1000
            batch = _get("/api/v3/klines", {"symbol": sym, "interval": interval, "startTime": cur, "limit": lim}, [SPOT_HOST])
        if not batch:
            break
        rows += batch
        cur = batch[-1][0] + 1
        if len(batch) < lim:
            break
    df = pd.DataFrame(rows, columns=list("tohlcv") + ["ct", "q", "n", "tb", "tq", "x"]).drop_duplicates("t")
    df = df[df["ct"] < now_ms]  # closed candles only
    out = pd.DataFrame({k: df[c].astype(float).values for k, c in (("open", "o"), ("high", "h"), ("low", "l"), ("close", "c"),
                                                                   ("volume", "v"))},
                       index=pd.to_datetime(df["t"].astype("int64").values, unit="ms", utc=True))
    return out


def _funding_monthly(sym: str, start: pd.Timestamp) -> pd.Series:
    """Monthly funding files from data.binance.vision; the months not published yet repeat the last month's average."""
    import io
    import zipfile
    parts, months = [], pd.period_range(start.tz_localize(None), pd.Timestamp.now(), freq="M")
    for m in months:
        try:
            r = requests.get(f"{VISION}/{sym}/{sym}-fundingRate-{m}.zip", timeout=20)
            if r.status_code != 200:
                continue
            with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                df = pd.read_csv(z.open(z.namelist()[0]))
            parts.append(pd.Series(df.iloc[:, 2].astype(float).values, index=pd.to_datetime(df.iloc[:, 0].astype("int64"), unit="ms", utc=True)))
        except (requests.RequestException, zipfile.BadZipFile, ValueError, IndexError):
            continue
    s = pd.concat(parts).sort_index() if parts else pd.Series(dtype=float)
    last = s.index[-1] if len(s) else start
    if len(s):
        recent = s[s.index > last - pd.Timedelta(days=30)].mean()
        fill = pd.date_range(last + pd.Timedelta(hours=8), pd.Timestamp.now(tz="UTC"), freq="8h")
        s = pd.concat([s, pd.Series(recent, index=fill)])
    return s[~s.index.duplicated()]


def funding(sym: str, start_ms: int) -> pd.Series:
    rows, cur, now_ms = [], start_ms, int(time.time() * 1000)
    while cur < now_ms:
        batch = _fapi("/fapi/v1/fundingRate", {"symbol": sym, "startTime": cur, "limit": 1000})
        if batch is None:
            SOURCE["funding"] = "monthly files"
            return _funding_monthly(sym, pd.Timestamp(start_ms, unit="ms", tz="UTC"))
        if not batch:
            break
        rows += batch
        cur = int(batch[-1]["fundingTime"]) + 1
        if len(batch) < 1000:
            break
    if not rows:
        return pd.Series(dtype=float)
    s = pd.Series([float(x["fundingRate"]) for x in rows],
                  index=pd.to_datetime([int(x["fundingTime"]) for x in rows], unit="ms", utc=True))
    return s[~s.index.duplicated()]


def atr14(h4: pd.DataFrame) -> np.ndarray:
    pc = h4["close"].shift()
    tr = pd.concat([h4["high"] - h4["low"], (h4["high"] - pc).abs(), (h4["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / 14, adjust=False).mean().to_numpy()


def flips(h4: pd.DataFrame) -> np.ndarray:
    ceiling = h4["high"].rolling(LOOKBACK).max().shift(1)
    above = h4["close"] > ceiling
    f = above & ~above.shift(1, fill_value=False)
    if VOL_MULT:
        loud = h4["volume"] > VOL_MULT * h4["volume"].rolling(VOL_WINDOW).mean().shift(1)
        f &= loud | (h4.index + H4 < VOL_FROM)
    f = f.to_numpy().copy()
    f[:max(LOOKBACK + 1, MIN_HISTORY - 1)] = False
    return f


def coin_trades(sym: str, h4: pd.DataFrame, h1: pd.DataFrame) -> list[dict]:
    """Every Donchian trade of one coin with entry >= PAPER_START (one position at a time per coin)."""
    hi, lo, op, cl = (h4[k].to_numpy(float) for k in ("high", "low", "open", "close"))
    atr, fl, idx = atr14(h4), flips(h4), h4.index
    trades, i, n = [], 0, len(h4)
    while i < n:
        if not fl[i] or idx[i] + H4 < PAPER_START or not atr[i] > 0:
            i += 1
            continue
        entry, sl0 = cl[i], cl[i] - K_ATR * atr[i]
        t = {"symbol": sym, "entry_time": idx[i] + H4, "entry": float(entry), "sl0": float(sl0), "stop": float(sl0),
             "extreme": float(entry), "status": "open", "reason": None, "exit_time": None, "exit_px": None,
             "ceiling": float(h4["high"].iloc[max(0, i - LOOKBACK):i].max())}
        stop, extreme, last, exit_k = sl0, entry, min(n - 1, i + MAX_BARS), None
        for k in range(i + 1, last + 1):
            if lo[k] <= stop:
                t.update(status="closed", reason="trail" if stop > sl0 else "sl", exit_px=float(min(stop, op[k])),
                         exit_time=idx[k] + H4)  # exact hour unknown inside the candle: booked at its close
                exit_k = k
                break
            extreme = max(extreme, hi[k])
            if not np.isnan(atr[k]):
                stop = max(stop, extreme - K_ATR * atr[k])
        else:
            if last - i >= MAX_BARS:
                t.update(status="closed", reason="time", exit_px=float(cl[last]), exit_time=idx[last] + H4)
                exit_k = last
        t.update(stop=float(stop), extreme=float(extreme), bars=int((exit_k if exit_k is not None else n - 1) - i))
        if t["status"] == "open":  # forming H4 candle, hour by hour (stop is fixed inside it)
            forming = h1[h1.index >= idx[-1] + H4]
            for ts, row in forming.iterrows():
                if row["low"] <= stop:
                    t.update(status="closed", reason="trail" if stop > sl0 else "sl", exit_px=float(min(stop, row["open"])),
                             exit_time=ts + pd.Timedelta(hours=1))
                    break
            if t["status"] == "open":
                t["extreme"] = float(max(extreme, forming["high"].max())) if len(forming) else float(extreme)
        trades.append(t)
        if t["status"] == "open":
            break
        i = exit_k if exit_k is not None else n  # the exit candle may itself be a new flip
    return trades


def portfolio(trades: list[dict], closes: dict, fund: dict, last_px: dict) -> tuple[list[dict], list[dict], dict]:
    """Compounding equity with RISK_PCT sizing, CAP, fees and funding. Returns (trades, curve, extra)."""
    events = []
    for n, t in enumerate(trades):
        events.append((t["entry_time"], 1, n))
        if t["status"] == "closed":
            events.append((t["exit_time"], 0, n))
    events.sort(key=lambda e: (e[0], e[1]))
    realized, open_pos, skipped, taken = EQUITY0, {}, 0, []
    for ts, kind, n in events:
        t = trades[n]
        if kind == 1:
            dist = (t["entry"] - t["sl0"]) / t["entry"]
            notional = realized * RISK_PCT / 100 / dist
            used = sum(trades[m]["notional"] for m in open_pos)
            if used + notional > CAP * realized:
                t["skipped"] = True
                skipped += 1
                continue
            t.update(skipped=False, notional=float(notional), qty=float(notional / t["entry"]), eq_at_entry=float(realized),
                     risk_usd=float(realized * RISK_PCT / 100))
            realized -= notional * FEE
            open_pos[n] = True
            taken.append(n)
        elif n in open_pos:
            del open_pos[n]
            f = fund.get(t["symbol"], pd.Series(dtype=float))
            fr = float(f[(f.index > t["entry_time"]) & (f.index <= t["exit_time"])].sum()) if len(f) else 0.0
            gross = t["notional"] * (t["exit_px"] / t["entry"] - 1)
            fees = t["notional"] * FEE * 2
            fcost = t["notional"] * fr
            t.update(pnl=float(gross - fees - fcost), fees=float(fees), funding=float(fcost),
                     r=float((t["exit_px"] - t["entry"]) / (t["entry"] - t["sl0"])))
            realized += gross - t["notional"] * FEE - fcost
    now = pd.Timestamp.now(tz="UTC")
    for n in open_pos:  # mark to market
        t = trades[n]
        px = last_px.get(t["symbol"], t["entry"])
        f = fund.get(t["symbol"], pd.Series(dtype=float))
        fr = float(f[f.index > t["entry_time"]].sum()) if len(f) else 0.0
        t.update(last=float(px), upnl=float(t["notional"] * (px / t["entry"] - 1) - t["notional"] * FEE - t["notional"] * fr),
                 funding=float(t["notional"] * fr), r=float((px - t["entry"]) / (t["entry"] - t["sl0"])))
    # equity curve, marked to market on every H4 close
    grid = pd.date_range(PAPER_START.floor("4h"), now.floor("4h"), freq="4h", tz="UTC")
    real = pd.Series(0.0, index=grid)
    for n in taken:
        t = trades[n]
        real[real.index >= t["entry_time"]] -= t["notional"] * FEE
        if t["status"] == "closed":
            real[real.index >= t["exit_time"]] += t["pnl"] + t["notional"] * FEE
    eq = real + EQUITY0
    for n in taken:
        t = trades[n]
        c = closes[t["symbol"]]
        end = t["exit_time"] if t["status"] == "closed" else now + H4
        win = (grid >= t["entry_time"]) & (grid < end)
        if win.any():
            px = c.reindex(grid[win] - H4).to_numpy()  # close of the candle that ended at that grid time
            px = pd.Series(px).ffill().fillna(t["entry"]).to_numpy()
            eq[win] += t["notional"] * (px / t["entry"] - 1)
    open_upnl = sum(trades[n]["upnl"] for n in open_pos)
    eq.iloc[-1] = realized + open_upnl
    curve = [[ts.strftime("%Y-%m-%d %H:%M"), round(float(v), 2)] for ts, v in eq.items()]
    return [trades[n] for n in taken], curve, {"skipped": skipped, "realized": realized, "open_upnl": open_upnl,
                                               "open_notional": sum(trades[n]["notional"] for n in open_pos)}


def tg_send(text: str) -> None:
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN", ""), os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat:
        return
    payload = {"chat_id": chat, "text": text, "disable_web_page_preview": True}
    url = os.getenv("WEBAPP_URL", "")
    if url.startswith("https://"):
        payload["reply_markup"] = {"inline_keyboard": [[{"text": "📊 Mở bảng theo dõi", "web_app": {"url": url}}]]}
    try:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json=payload, timeout=10)
    except requests.RequestException as exc:
        print("[WARN] telegram:", exc)


def px(x: float) -> str:
    return f"{x:,.2f}" if abs(x) >= 100 else f"{x:,.4f}" if abs(x) >= 1 else f"{x:,.6f}"


def main() -> int:
    prev = {}
    if OUT.exists():
        try:
            prev = json.loads(OUT.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            prev = {}
    deployed = prev.get("meta", {}).get("deployed_at") or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    warm = int((PAPER_START - pd.Timedelta(days=75)).timestamp() * 1000)
    all_trades, closes, fund, last_px, radar = [], {}, {}, {}, []
    for sym in SYMBOLS:
        h4 = klines(sym, "4h", warm)
        h1 = klines(sym, "1h", int((h4.index[-1] - pd.Timedelta(hours=8)).timestamp() * 1000))
        fund[sym] = funding(sym, int(PAPER_START.timestamp() * 1000))
        closes[sym] = h4["close"]
        last_px[sym] = float(h1["close"].iloc[-1]) if len(h1) else float(h4["close"].iloc[-1])
        tr = coin_trades(sym, h4, h1)
        all_trades += tr
        a = atr14(h4)
        ceiling = float(h4["high"].iloc[-LOOKBACK:].max())  # what the next closed candle must beat
        above_now = bool(h4["close"].iloc[-1] > float(h4["high"].iloc[-LOOKBACK - 1:-1].max()))
        radar.append({"symbol": sym, "price": last_px[sym], "ceiling": ceiling,
                      "gap_pct": round((ceiling / last_px[sym] - 1) * 100, 2), "atr_pct": round(a[-1] / h4["close"].iloc[-1] * 100, 2),
                      "in_position": bool(tr and tr[-1]["status"] == "open"), "above": above_now,
                      "spark": [round(float(v), 6) for v in h4["close"].iloc[-60:]]})
        print(f"[{sym}] {len(h4)} H4 bars, {len(tr)} trades", flush=True)
    taken, curve, extra = portfolio(all_trades, closes, fund, last_px)
    closed = [t for t in taken if t["status"] == "closed"]
    opened = [t for t in taken if t["status"] == "open"]
    eqs = np.array([v for _, v in curve])
    peak = np.maximum.accumulate(eqs)
    dd = (eqs / peak - 1) * 100
    wins = [t for t in closed if t["pnl"] > 0]
    gl = -sum(t["pnl"] for t in closed if t["pnl"] <= 0)
    final = float(eqs[-1])
    yrs = max((pd.Timestamp.now(tz="UTC") - PAPER_START).days / 365.25, 1 / 365.25)

    def fmt_t(t: dict) -> dict:
        d = {k: (v.strftime("%Y-%m-%d %H:%M") if isinstance(v, pd.Timestamp) else v) for k, v in t.items()}
        d["backfill"] = d["entry_time"] < deployed
        d["id"] = f"{t['symbol']}|{d['entry_time']}"
        return {k: (round(v, 8) if isinstance(v, float) else v) for k, v in d.items()}

    out = {
        "meta": {"updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"), "deployed_at": deployed,
                 "paper_start": PAPER_START.strftime("%Y-%m-%d"), "equity0": EQUITY0, "risk_pct": RISK_PCT,
                 "lookback": LOOKBACK, "trail_atr": K_ATR, "cap": CAP, "vol_mult": VOL_MULT, "vol_from": f"{VOL_FROM:%Y-%m-%d}", "fee_pct": round(FEE * 100, 4), "symbols": SYMBOLS, "source": dict(SOURCE)},
        "stats": {"equity": round(final, 2), "ret_pct": round((final / EQUITY0 - 1) * 100, 2),
                  "cagr_pct": round(((final / EQUITY0) ** (1 / yrs) - 1) * 100, 2) if yrs >= 0.5 else None,
                  "max_dd_pct": round(float(dd.min()), 2), "cur_dd_pct": round(float(dd[-1]), 2),
                  "peak": round(float(peak[-1]), 2), "trades": len(closed), "wins": len(wins),
                  "winrate": round(len(wins) / len(closed) * 100, 1) if closed else None,
                  "pf": round(sum(t["pnl"] for t in wins) / gl, 2) if gl > 0 else None,
                  "sum_r": round(sum(t["r"] for t in closed), 2), "avg_r": round(float(np.mean([t["r"] for t in closed])), 2) if closed else None,
                  "best_r": round(max((t["r"] for t in closed), default=0), 2), "open": len(opened),
                  "open_upnl": round(extra["open_upnl"], 2), "exposure_x": round(extra["open_notional"] / final, 2) if final > 0 else 0,
                  "skipped": extra["skipped"], "fees": round(sum(t.get("fees", 0) for t in closed), 2),
                  "funding": round(sum(t.get("funding", 0) for t in taken), 2)},
        "open": [fmt_t(t) for t in sorted(opened, key=lambda t: t["entry_time"])],
        "closed": [fmt_t(t) for t in sorted(closed, key=lambda t: t["exit_time"], reverse=True)],
        "radar": sorted(radar, key=lambda r: (not r["in_position"], r["gap_pct"])),
        "curve": curve,
    }
    # alerts for events that appeared since the previous run (never for backfill)
    seen_open = {t["id"] for t in prev.get("open", [])} | {t["id"] for t in prev.get("closed", [])}
    seen_closed = {t["id"] for t in prev.get("closed", [])}
    if prev:
        for t in out["open"] + out["closed"]:
            if t["id"] not in seen_open and not t["backfill"]:
                tg_send(f"🚀 [PAPER] LONG {t['symbol']} @ {px(t['entry'])} · SL {px(t['sl0'])} "
                        f"({(t['sl0'] / t['entry'] - 1) * 100:+.1f}%) · notional ${t['notional']:,.0f} · rủi ro ${t['risk_usd']:,.0f}")
        for t in out["closed"]:
            if t["id"] not in seen_closed and not t["backfill"]:
                why = {"sl": "SL ban đầu", "trail": "trailing", "time": "hết 30 ngày"}.get(t["reason"], t["reason"])
                tg_send(f"{'✅' if t['pnl'] > 0 else '❌'} [PAPER] Đóng {t['symbol']} ({why}) @ {px(t['exit_px'])} · "
                        f"{t['r']:+.2f}R · {t['pnl']:+,.0f}$ · vốn ${final:,.0f}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8", newline="\n")
    s = out["stats"]
    print(f"[OK] equity ${s['equity']:,.0f} ({s['ret_pct']:+.1f}%) dd {s['max_dd_pct']}% trades {s['trades']} open {s['open']} "
          f"pf {s['pf']} -> {OUT}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
