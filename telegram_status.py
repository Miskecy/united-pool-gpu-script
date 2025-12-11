import os
import json
import time
import re
import hashlib
from datetime import datetime
import requests

_TOKEN = ""
_CHAT = ""
_WORKER = ""
_STATE_PATH = "telegram_state.json"
_STATUS_MESSAGE_ID = None
_LAST_HASH = {}
_LAST_TS = {}
_LOGGER = None

def configure_telegram(token, chat_id, worker_name, state_file, logger=None):
    global _TOKEN, _CHAT, _WORKER, _STATE_PATH, _LOGGER
    _TOKEN = token or ""
    _CHAT = str(chat_id or "")
    _WORKER = worker_name or ""
    _STATE_PATH = state_file or _STATE_PATH
    _LOGGER = logger

def _log(level, message):
    try:
        if _LOGGER:
            _LOGGER(level, message)
        else:
            ts = time.strftime("[%Y-%m-%d.%H:%M:%S]", time.localtime())
            print(f"{ts} [{level}] {message}")
    except Exception:
        pass

def _status_key():
    return f"{_CHAT}::{_WORKER or 'default'}"

def _load_state():
    try:
        if os.path.exists(_STATE_PATH):
            with open(_STATE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
    except Exception:
        pass
    return {}

def _save_state(state):
    try:
        with open(_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f)
    except Exception:
        pass

def _ensure_status_message(initial_text):
    global _STATUS_MESSAGE_ID
    if not _TOKEN or not _CHAT:
        return None
    if _STATUS_MESSAGE_ID is None:
        st = _load_state()
        key = _status_key()
        mid = st.get(key)
        if isinstance(mid, int):
            _STATUS_MESSAGE_ID = mid
        else:
            url = f"https://api.telegram.org/bot{_TOKEN}/sendMessage"
            payload = {
                "chat_id": str(_CHAT),
                "text": initial_text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }
            try:
                r = requests.post(url, data=payload, timeout=10)
                if r.status_code == 200:
                    js = {}
                    try:
                        js = r.json() or {}
                    except Exception:
                        js = {}
                    msg = js.get("result") or {}
                    _STATUS_MESSAGE_ID = int(msg.get("message_id")) if msg.get("message_id") is not None else None
                    if _STATUS_MESSAGE_ID is not None:
                        st[key] = _STATUS_MESSAGE_ID
                        try:
                            h = hashlib.sha256((initial_text or "").encode("utf-8")).hexdigest()
                            st[f"{key}::last_hash"] = h
                        except Exception:
                            pass
                        _save_state(st)
                else:
                    snip = ""
                    try:
                        snip = (r.text or "")[:200].replace("\n", " ")
                    except Exception:
                        pass
                    _log("Error", f"Error creating Telegram status message: {r.status_code} {snip}")
                    try:
                        plain = re.sub(r"<[^>]+>", "", initial_text)
                        r2 = requests.post(url, data={
                            "chat_id": str(_CHAT),
                            "text": plain,
                            "disable_web_page_preview": True,
                        }, timeout=10)
                        if r2.status_code == 200:
                            js2 = {}
                            try:
                                js2 = r2.json() or {}
                            except Exception:
                                js2 = {}
                            msg2 = js2.get("result") or {}
                            _STATUS_MESSAGE_ID = int(msg2.get("message_id")) if msg2.get("message_id") is not None else None
                            if _STATUS_MESSAGE_ID is not None:
                                st[key] = _STATUS_MESSAGE_ID
                                try:
                                    h2 = hashlib.sha256((plain or "").encode("utf-8")).hexdigest()
                                    st[f"{key}::last_hash"] = h2
                                except Exception:
                                    pass
                                _save_state(st)
                    except Exception:
                        pass
            except requests.RequestException:
                _log("Error", "Request error while creating Telegram status message.")
    return _STATUS_MESSAGE_ID

def _escape_html(s):
    try:
        t = "" if s is None else str(s)
        return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    except Exception:
        return ""

def _format_duration(seconds):
    s = int(max(0, seconds or 0))
    w = s // 604800
    s %= 604800
    d = s // 86400
    s %= 86400
    h = s // 3600
    s %= 3600
    m = s // 60
    s %= 60
    parts = []
    if w:
        parts.append(f"{w} week" + ("s" if w != 1 else ""))
    if d:
        parts.append(f"{d} day" + ("s" if d != 1 else ""))
    if h:
        parts.append(f"{h} hour" + ("s" if h != 1 else ""))
    if m:
        parts.append(f"{m} min" + ("s" if m != 1 else ""))
    if not parts:
        parts.append(f"{s} sec" + ("s" if s != 1 else ""))
    return " ".join(parts)

def format_status_html(status):
    sid = _escape_html(status.get("session_id", ""))
    started = status.get("session_started_ts", 0)
    now_ts = time.time()
    dur = int(max(0, now_ts - (started or 0)))
    active = _escape_html(_format_duration(dur))
    blocks = status.get("session_blocks", 0)
    consec = status.get("session_consecutive", 0)
    gpu = _escape_html(status.get("gpu", ""))
    alg = _escape_html(status.get("algorithm", ""))
    rng = _escape_html(status.get("range", ""))
    addrs = status.get("addresses", 0)
    pending = status.get("pending_keys", 0)
    last_batch = _escape_html(status.get("last_batch", "-"))
    last_error = _escape_html(status.get("last_error", "-"))
    keyfound = _escape_html(status.get("keyfound", "-"))
    next_in = status.get("next_fetch_in", 0)
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    lines = [
        "📊 <b>Status</b>",
        f"🧩 <b>Session</b>: <code>{sid}</code>",
        f"⏳ <b>Active</b>: <code>{active}</code>",
        f"✅ <b>Blocks</b>: <code>{blocks}</code>",
        f"🔁 <b>Consecutive</b>: <code>{consec}</code>",
        f"⚙️ <b>GPU</b>: <code>{gpu}</code>",
        f"🧠 <b>Algorithm</b>: <code>{alg}</code>",
        f"🧭 <b>Range</b>: <code>{rng}</code>",
        f"📫 <b>Addresses</b>: <code>{addrs}</code>",
        f"📦 <b>Pending Keys</b>: <code>{pending}</code>",
        f"📤 <b>Last Batch</b>: <code>{last_batch}</code>",
        f"❗ <b>Last Error</b>: <i>{last_error}</i>",
        f"🔑 <b>Keyfound</b>: <code>{keyfound}</code>",
        f"⏱️ <b>Next Fetch</b>: <code>{next_in}s</code>",
        f"🕒 <i>Updated {ts}</i>",
    ]
    if status.get("all_blocks_solved", False):
        lines.append("🏁 <b>All blocks solved</b> ✅")
    return "\n".join(lines)

def edit_status(message):
    if not _TOKEN or not _CHAT:
        _log("Warning", "Telegram settings missing. Notification not sent.")
        return
    if _WORKER:
        w = _escape_html(_WORKER)
        message = f"👷 <b>Worker</b>: <code>{w}</code>\n\n{message}"
    mid = _ensure_status_message(message)
    if not mid:
        return
    key = _status_key()
    st = _load_state()
    new_hash = hashlib.sha256((message or "").encode("utf-8")).hexdigest()
    last_hash = st.get(f"{key}::last_hash")
    if last_hash == new_hash:
        _log("Info", "Telegram status unchanged; skipped edit")
        return
    url = f"https://api.telegram.org/bot{_TOKEN}/editMessageText"
    payload = {
        "chat_id": str(_CHAT),
        "message_id": mid,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        r = requests.post(url, data=payload, timeout=10)
        if r.status_code == 200:
            st[f"{key}::last_hash"] = new_hash
            _save_state(st)
            _log("Success", "Telegram status updated")
        else:
            desc = ""
            try:
                js = r.json() or {}
                desc = str(js.get("description", ""))
            except Exception:
                desc = ""
            if "message is not modified" in desc.lower():
                st[f"{key}::last_hash"] = new_hash
                _save_state(st)
                _log("Info", "Telegram edit skipped: message not modified")
            else:
                st.pop(key, None)
                _save_state(st)
                _STATUS_MESSAGE_ID = None
                _ensure_status_message(message)
                snippet = ""
                try:
                    snippet = (r.text or "")[:120].replace("\n", " ")
                except Exception:
                    pass
                _log("Warning", f"Edit failed ({r.status_code}). Recreated status message. {snippet}")
    except requests.RequestException:
        _log("Error", "Request error while editing Telegram message.")

def send_notification(message):
    edit_status(message)

def update_status(status, fields=None, gpu_fallback="-"):
    if fields:
        for k, v in fields.items():
            status[k] = v
    if not status.get("gpu"):
        status["gpu"] = str(gpu_fallback)
    status["updated_at"] = datetime.now().isoformat(timespec="seconds")
    edit_status(format_status_html(status))

def update_status_rl(status, fields, category, min_interval, gpu_fallback="-"):
    now = time.time()
    last = _LAST_TS.get(category, 0)
    if now - last < min_interval:
        return
    _LAST_TS[category] = now
    update_status(status, fields, gpu_fallback)

def send_notification_rl(message, category, min_interval):
    now = time.time()
    last = _LAST_TS.get(category, 0)
    if now - last < min_interval:
        return
    _LAST_TS[category] = now
    send_notification(message)
