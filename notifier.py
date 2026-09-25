"""Notificações via Telegram (reutiliza o bot Roco)."""

from __future__ import annotations

import json
import logging

import requests

import config
import db

log = logging.getLogger(__name__)


def send_message(text: str) -> bool:
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        log.info("telegram não configurado; notificação ignorada")
        return False
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": config.TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=15,
        )
        resp.raise_for_status()
        return True
    except requests.RequestException as exc:
        log.warning("telegram falhou: %s", exc)
        return False


def notify_new_opportunities(conn) -> int:
    rows = db.list_opportunities(conn, "tradeup", robust_only=True)
    fresh = [
        r
        for r in rows
        if r.get("ev_net", 0) >= config.NOTIFY_MIN_EV
    ][:5]
    if not fresh:
        return 0

    already = set()
    raw = db.get_setting(conn, "notified_tradeup_keys")
    if raw:
        try:
            already = set(json.loads(raw))
        except ValueError:
            already = set()

    new_rows = [r for r in fresh if r["key"] not in already]
    if not new_rows:
        return 0

    lines = ["🎯 <b>SrRobs Skin Trader Pro</b> — novas oportunidades robustas"]
    for r in new_rows:
        lines.append(
            f"• {r['mix']} → EV {r['ev_net']:.2f} {config.CURRENCY} "
            f"(ROI {r['roi_pct']:.1f}%)"
        )
    sent = send_message("\n".join(lines))
    if sent:
        already.update(r["key"] for r in new_rows)
        db.set_setting(conn, "notified_tradeup_keys", json.dumps(sorted(already)))
    return len(new_rows)


def notify_lock_ends(conn, ready_positions: list[dict]) -> None:
    for pos in ready_positions:
        flag_key = f"notified_lock_end_{pos['id']}"
        if db.get_setting(conn, flag_key):
            continue
        profit = (
            f"{pos['current_profit']:+.2f} {config.CURRENCY}"
            if pos.get("current_profit") is not None
            else "s/d"
        )
        ok = send_message(
            f"🔓 <b>Lock terminado</b>\n"
            f"{pos['name']} ×{pos['quantity']}\n"
            f"Sugestão: <b>{pos['suggestion']}</b>\n"
            f"Lucro estimado: {profit}"
        )
        if ok:
            db.set_setting(conn, flag_key, "1")
