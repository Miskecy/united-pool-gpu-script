# -*- coding: utf-8 -*-
"""
Main worker script: fetch work blocks, run the external key cracker
(VanitySearch or BitCrack), parse results, and notify status/errors via Telegram.
"""
import requests
import os
import subprocess
import time
import sys
from datetime import datetime
from colorama import Fore, Style, init
import json
import shlex
import re
import uuid
import hashlib
import threading
from output_parsers import parse_out
from telegram_status import (
    configure_telegram,
    update_status as _tg_update_status,
    update_status_rl as _tg_update_status_rl,
    send_notification as _tg_send,
    send_notification_rl as _tg_send_rl,
)

def _load_settings():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base_dir, "settings.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

_SETTINGS = _load_settings()

# --- File Configuration ---
IN_FILE = "in.txt"
OUT_FILE = "out.txt"
KEYFOUND_FILE = "KEYFOUND.txt"

TELEGRAM_BOT_TOKEN = ""
TELEGRAM_CHAT_ID = ""
API_URL = ""
POOL_TOKEN = ""
ADDITIONAL_ADDRESSES = []
BLOCK_LENGTH = ""
APP_PATH = ""
APP_ARGS = ""
PROGRAM_KIND = "vanity"
WORKER_NAME = ""
SEND_ADDITIONAL_KEYS_TO_API = False

ONE_SHOT = False
POST_BLOCK_DELAY_SECONDS = 10
POST_BLOCK_DELAY_ENABLED = True

TELEGRAM_STATE_FILE = "telegram_state.json"
STATUS_MESSAGE_ID = None
LAST_MESSAGE_HASH = None

def _apply_settings(s):
    global TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, API_URL, POOL_TOKEN, ADDITIONAL_ADDRESSES, BLOCK_LENGTH
    global APP_PATH, APP_ARGS, PROGRAM_KIND, WORKER_NAME, ONE_SHOT
    global POST_BLOCK_DELAY_SECONDS, POST_BLOCK_DELAY_ENABLED
    TELEGRAM_BOT_TOKEN = s.get("telegram_accesstoken", "")
    TELEGRAM_CHAT_ID = str(s.get("telegram_chatid", ""))
    API_URL = str(s.get("api_url", ""))
    try:
        API_URL = API_URL.strip().strip("`")
    except Exception:
        pass
    POOL_TOKEN = s.get("user_token", "")
    addrs = s.get("additional_addresses", [])
    if isinstance(addrs, list):
        ADDITIONAL_ADDRESSES = [a for a in addrs if isinstance(a, str) and a.strip()]
    else:
        ADDITIONAL_ADDRESSES = []
    legacy_addr = s.get("additional_address", "")
    if isinstance(legacy_addr, str) and legacy_addr.strip() and legacy_addr not in ADDITIONAL_ADDRESSES:
        ADDITIONAL_ADDRESSES.append(legacy_addr)
    BLOCK_LENGTH = s.get("block_length", "")
    APP_PATH = s.get("program_path")
    APP_ARGS = s.get("program_arguments")
    PROGRAM_KIND = str(s.get("program_name", "")).strip().lower()
    if PROGRAM_KIND and "|" in PROGRAM_KIND:
        PROGRAM_KIND = PROGRAM_KIND.split("|")[0].strip().lower()
    WORKER_NAME = s.get("worker_name", "") or s.get("workername", "")
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        if APP_PATH and "|" in APP_PATH:
            cands = [p.strip() for p in APP_PATH.split("|") if p.strip()]
            for p in cands:
                cand = p if os.path.isabs(p) else os.path.normpath(os.path.join(base_dir, p))
                if os.path.exists(cand):
                    APP_PATH = cand
                    break
        if APP_PATH and not os.path.isabs(APP_PATH):
            APP_PATH = os.path.normpath(os.path.join(base_dir, APP_PATH))
    except Exception:
        pass
    ONE_SHOT = bool(s.get("oneshot", False))
    try:
        SEND_ADDITIONAL_KEYS_TO_API = bool(s.get("send_additional_keys_to_api", False))
    except Exception:
        SEND_ADDITIONAL_KEYS_TO_API = False
    try:
        POST_BLOCK_DELAY_ENABLED = bool(s.get("post_block_delay_enabled", True))
    except Exception:
        POST_BLOCK_DELAY_ENABLED = True
    if POST_BLOCK_DELAY_ENABLED:
        delay_min = s.get("post_block_delay_minutes")
        try:
            if delay_min is not None:
                dm = float(delay_min)
                if dm < 0:
                    dm = 0
                POST_BLOCK_DELAY_SECONDS = int(dm * 60)
            else:
                POST_BLOCK_DELAY_SECONDS = 10
        except Exception:
            POST_BLOCK_DELAY_SECONDS = 10
    else:
        POST_BLOCK_DELAY_SECONDS = 0

def refresh_settings():
    s = _load_settings()
    _apply_settings(s)
    try:
        configure_telegram(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, WORKER_NAME, TELEGRAM_STATE_FILE, logger)
    except Exception:
        pass

_apply_settings(_SETTINGS)
try:
    configure_telegram(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, WORKER_NAME, TELEGRAM_STATE_FILE, logger)
except Exception:
    pass

# Initialize colorama
init(autoreset=True)

PENDING_KEYS = []
previous_keyspace = None
CURRENT_ADDR_COUNT = 10
CURRENT_RANGE_START = None
CURRENT_RANGE_END = None
PENDING_KEYS_FILE = "pending_keys.json"
LAST_POST_ATTEMPT = 0
ALL_BLOCKS_SOLVED = False
PROCESSED_ONE_BLOCK = False
NEED_NEW_BLOCK_FETCH = False
LAST_RUN_OK = False
POST_ERROR_CONSECUTIVE = 0

GPU_LABEL_CACHE = None

def _detect_gpu_label():
    global GPU_LABEL_CACHE
    if GPU_LABEL_CACHE is not None:
        return GPU_LABEL_CACHE
    label = "-"
    try:
        if APP_PATH:
            cmd = [APP_PATH, "-l"]
            with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True) as p:
                try:
                    out, _ = p.communicate(timeout=10)
                except Exception:
                    try:
                        p.kill()
                    except Exception:
                        pass
                    out = ""
            lines = [ln.strip() for ln in (out or "").splitlines()]
            target = None
            gpu_id = 0
            try:
                m = re.search(r"-gpuId\s+(\d+)", str(APP_ARGS or ""))
                if m:
                    gpu_id = int(m.group(1))
            except Exception:
                gpu_id = 0
            for ln in lines:
                if re.match(rf"^\s*GPU\s*#?{gpu_id}\b", ln, re.IGNORECASE):
                    target = ln.strip()
                    break
            if target:
                name = target
                idx = name.find("(")
                if idx > 0:
                    name = name[:idx].strip()
                label = name
    except Exception:
        label = "-"
    GPU_LABEL_CACHE = label
    return label

def _detect_gpu_labels():
    try:
        labels = []
        if APP_PATH:
            cmd = [APP_PATH, "-l"]
            with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True) as p:
                try:
                    out, _ = p.communicate(timeout=10)
                except Exception:
                    try:
                        p.kill()
                    except Exception:
                        pass
                    out = ""
            lines = [ln.strip() for ln in (out or "").splitlines()]
            for ln in lines:
                m = re.match(r"^\s*GPU\s*#?(\d+)\b(.+)$", ln, re.IGNORECASE)
                if m:
                    gid = m.group(1)
                    name = m.group(2).strip()
                    idx = name.find("(")
                    if idx > 0:
                        name = name[:idx].strip()
                    labels.append(f"GPU#{gid} {name}")
        if labels:
            return labels
    except Exception:
        pass
    return []

def _detect_gpu_list():
    try:
        if APP_PATH:
            cmd = [APP_PATH, "-l"]
            with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True) as p:
                try:
                    out, _ = p.communicate(timeout=10)
                except Exception:
                    try:
                        p.kill()
                    except Exception:
                        pass
                    out = ""
            lines = [ln.strip() for ln in (out or "").splitlines()]
            ids = []
            for ln in lines:
                m = re.match(r"^\s*GPU\s*#?(\d+)\b", ln, re.IGNORECASE)
                if m:
                    try:
                        ids.append(int(m.group(1)))
                    except Exception:
                        pass
            if ids:
                ids = sorted(list(set(ids)))
                return ids
    except Exception:
        pass
    return [0]

def _program_label():
    try:
        path = APP_PATH or ""
        if path:
            base = os.path.basename(path)
            name, _ext = os.path.splitext(base)
            return name or base or "-"
        raw = (PROGRAM_KIND or "").strip()
        return raw or "-"
    except Exception:
        return "-"

def _status_program_args():
    try:
        s = (APP_ARGS or "").strip()
        return s or "-"
    except Exception:
        return "-"

STATUS = {
    "worker": "",
    "gpu": "",
    "range": "",
    "addresses": 0,
    "pending_keys": 0,
    "last_batch": "-",
    "last_error": "-",
    "keyfound": "-",
    "all_blocks_solved": False,
    "next_fetch_in": 0,
    "updated_at": "",
}

ERROR_COUNTS = {}

def _record_error(category):
    try:
        c = int(ERROR_COUNTS.get(category, 0)) + 1
        ERROR_COUNTS[category] = c
        return c
    except Exception:
        return 1

def notify_error(category, message, api_offline=False, sleep_seconds=0, rate_limit=300):
    try:
        update_status_rl({"last_error": str(message)}, category, rate_limit)
    except Exception:
        pass
    try:
        logger("Error", str(message))
    except Exception:
        pass
    if api_offline:
        try:
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)
        except Exception:
            pass
        return
    cnt = _record_error(category)
    if cnt >= 3:
        try:
            send_telegram_notification(f"❌ Error threshold reached in '{category}'. Resetting state.")
        except Exception:
            pass
        try:
            PENDING_KEYS = []
            _save_pending_keys()
        except Exception:
            pass
        try:
            if os.path.exists(PENDING_KEYS_FILE):
                os.remove(PENDING_KEYS_FILE)
        except Exception:
            pass
        try:
            clean_io_files()
        except Exception:
            pass
        try:
            globals()["NEED_NEW_BLOCK_FETCH"] = True
        except Exception:
            pass
        return

def _load_pending_keys():
    global PENDING_KEYS
    try:
        if os.path.exists(PENDING_KEYS_FILE):
            with open(PENDING_KEYS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    PENDING_KEYS = data
    except Exception:
        pass

def _save_pending_keys():
    try:
        with open(PENDING_KEYS_FILE, "w", encoding="utf-8") as f:
            json.dump(PENDING_KEYS, f)
    except Exception:
        pass

def _retry_pending_keys_now():
    global PENDING_KEYS, NEED_NEW_BLOCK_FETCH
    posted = False
    required = max(10, min(30, int(CURRENT_ADDR_COUNT or 10)))
    while len(PENDING_KEYS) >= required:
        batch = PENDING_KEYS[:required]
        _res = post_private_keys(batch)
        _ok = _res[0] if isinstance(_res, tuple) else bool(_res)
        _incomp = _res[1] if isinstance(_res, tuple) else False
        if _ok:
            PENDING_KEYS = PENDING_KEYS[required:]
            posted = True
            _save_pending_keys()
        else:
            if _incomp:
                PENDING_KEYS = []
                _save_pending_keys()
                NEED_NEW_BLOCK_FETCH = True
                break
            else:
                _save_pending_keys()
                break
    # If we have some keys but fewer than required, try filling with randoms in current range
    if not posted and LAST_RUN_OK and 0 < len(PENDING_KEYS) < required and CURRENT_RANGE_START and CURRENT_RANGE_END:
        fillers = _generate_filler_keys(required - len(PENDING_KEYS), CURRENT_RANGE_START, CURRENT_RANGE_END, exclude=PENDING_KEYS)
        batch = PENDING_KEYS + fillers
        if len(batch) == required:
            _res = post_private_keys(batch)
            _ok = _res[0] if isinstance(_res, tuple) else bool(_res)
            _incomp = _res[1] if isinstance(_res, tuple) else False
            if _ok:
                PENDING_KEYS = []
                posted = True
                _save_pending_keys()
            elif _incomp:
                PENDING_KEYS = []
                _save_pending_keys()
                NEED_NEW_BLOCK_FETCH = True
    return posted

def _scheduled_pending_post_retry():
    global LAST_POST_ATTEMPT
    now = time.time()
    required = max(10, min(30, int(CURRENT_ADDR_COUNT or 10)))
    if now - LAST_POST_ATTEMPT >= 30 and len(PENDING_KEYS) >= required:
        LAST_POST_ATTEMPT = now
        ok = _retry_pending_keys_now()
        if ok:
            logger("Success", "Pending keys posted successfully.")
        else:
            logger("Warning", "API unavailable. Keeping keys and retrying in 30s.")

def flush_pending_keys_blocking():
    global PENDING_KEYS, NEED_NEW_BLOCK_FETCH
    posted = False
    required = max(10, min(30, int(CURRENT_ADDR_COUNT or 10)))
    while len(PENDING_KEYS) >= required:
        batch = PENDING_KEYS[:required]
        _res = post_private_keys(batch)
        _ok = _res[0] if isinstance(_res, tuple) else bool(_res)
        _incomp = _res[1] if isinstance(_res, tuple) else False
        if _ok:
            PENDING_KEYS = PENDING_KEYS[required:]
            posted = True
            _save_pending_keys()
        else:
            if _incomp:
                PENDING_KEYS = []
                _save_pending_keys()
                NEED_NEW_BLOCK_FETCH = True
                break
            else:
                _save_pending_keys()
                if 'NEED_NEW_BLOCK_FETCH' in globals() and NEED_NEW_BLOCK_FETCH:
                    break
                time.sleep(30)
    # Try a final post with fillers if we have some keys but fewer than required
    if not posted and LAST_RUN_OK and 0 < len(PENDING_KEYS) < required and CURRENT_RANGE_START and CURRENT_RANGE_END:
        fillers = _generate_filler_keys(required - len(PENDING_KEYS), CURRENT_RANGE_START, CURRENT_RANGE_END, exclude=PENDING_KEYS)
        batch = PENDING_KEYS + fillers
        if len(batch) == required:
            _res = post_private_keys(batch)
            _ok = _res[0] if isinstance(_res, tuple) else bool(_res)
            _incomp = _res[1] if isinstance(_res, tuple) else False
            if _ok:
                PENDING_KEYS = []
                posted = True
                _save_pending_keys()
            else:
                if _incomp:
                    PENDING_KEYS = []
                    _save_pending_keys()
                    NEED_NEW_BLOCK_FETCH = True
                else:
                    if 'NEED_NEW_BLOCK_FETCH' in globals() and NEED_NEW_BLOCK_FETCH:
                        pass
                    else:
                        time.sleep(30)
    return posted

def handle_next_block_immediately():
    refresh_settings()
    data = fetch_block_data()
    if not data:
        return False
    addresses = data.get("checkwork_addresses", [])
    range_data = data.get("range", {})
    start_hex = range_data.get("start", "").replace("0x", "")
    end_hex = range_data.get("end", "").replace("0x", "")
    keyspace = f"{start_hex}:{end_hex}"
    global previous_keyspace
    previous_keyspace = keyspace
    # Track current dynamic requirements
    try:
        global CURRENT_ADDR_COUNT, CURRENT_RANGE_START, CURRENT_RANGE_END
        CURRENT_ADDR_COUNT = int(len(addresses) or 10)
        CURRENT_RANGE_START = start_hex
        CURRENT_RANGE_END = end_hex
    except Exception:
        pass
    save_addresses_to_in_file(addresses, ADDITIONAL_ADDRESSES)
    run_external_program(start_hex, end_hex)
    return True
# ==============================================================================================
#                                    UTILITY & COMMUNICATION FUNCTIONS
# ==============================================================================================

def logger(level, message):
    """
    Print a message with timestamp and colored log level.
    """
    current_time = datetime.now()
    formatted_time = current_time.strftime("[%Y-%m-%d.%H:%M:%S]")
    
    color_map = {
        "Info": Fore.LIGHTBLUE_EX,
        "Warning": Fore.LIGHTYELLOW_EX,
        "Error": Fore.LIGHTRED_EX,
        "Success": Fore.LIGHTGREEN_EX,
        "KEYFOUND": Fore.LIGHTMAGENTA_EX,
        "Timer": Fore.LIGHTYELLOW_EX
    }
    
    color = color_map.get(level, Fore.WHITE)
    print(f"{formatted_time} {color}[{level}]{Style.RESET_ALL} {message}")

# ----------------------------------------------------------------------------------------------

def _load_telegram_state():
    try:
        if os.path.exists(TELEGRAM_STATE_FILE):
            with open(TELEGRAM_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
    except Exception:
        pass
    return {}

def _save_telegram_state(state):
    try:
        with open(TELEGRAM_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f)
    except Exception:
        pass

def _status_key():
    return f"{str(TELEGRAM_CHAT_ID)}::{WORKER_NAME or 'default'}"

def _ensure_status_message(initial_text):
    global STATUS_MESSAGE_ID
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return None
    if STATUS_MESSAGE_ID is None:
        st = _load_telegram_state()
        key = _status_key()
        mid = st.get(key)
        if isinstance(mid, int):
            STATUS_MESSAGE_ID = mid
        else:
            telegram_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            payload = {
                "chat_id": str(TELEGRAM_CHAT_ID),
                "text": initial_text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }
            try:
                r = requests.post(telegram_url, data=payload, timeout=10)
                if r.status_code == 200:
                    js = {}
                    try:
                        js = r.json() or {}
                    except Exception:
                        js = {}
                    msg = js.get("result") or {}
                    STATUS_MESSAGE_ID = int(msg.get("message_id")) if msg.get("message_id") is not None else None
                    if STATUS_MESSAGE_ID is not None:
                        st[key] = STATUS_MESSAGE_ID
                        try:
                            h = hashlib.sha256((initial_text or "").encode("utf-8")).hexdigest()
                            st[f"{key}::last_hash"] = h
                        except Exception:
                            pass
                        _save_telegram_state(st)
                else:
                    snip = ""
                    try:
                        snip = (r.text or "")[:200].replace("\n", " ")
                    except Exception:
                        pass
                    logger("Error", f"Error creating Telegram status message: {r.status_code} {snip}")
                    try:
                        plain = re.sub(r"<[^>]+>", "", initial_text)
                        r2 = requests.post(telegram_url, data={
                            "chat_id": str(TELEGRAM_CHAT_ID),
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
                            STATUS_MESSAGE_ID = int(msg2.get("message_id")) if msg2.get("message_id") is not None else None
                            if STATUS_MESSAGE_ID is not None:
                                st[key] = STATUS_MESSAGE_ID
                                try:
                                    h2 = hashlib.sha256((plain or "").encode("utf-8")).hexdigest()
                                    st[f"{key}::last_hash"] = h2
                                except Exception:
                                    pass
                                _save_telegram_state(st)
                    except Exception:
                        pass
            except requests.RequestException:
                logger("Error", "Request error while creating Telegram status message.")
    return STATUS_MESSAGE_ID

def edit_telegram_status(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger("Warning", "Telegram settings missing. Notification not sent.")
        return
    if WORKER_NAME:
        w = _escape_html(WORKER_NAME)
        message = f"👷 <b>Worker</b>: <code>{w}</code>\n\n{message}"
    mid = _ensure_status_message(message)
    if not mid:
        return
    try:
        key = _status_key()
        st = _load_telegram_state()
        new_hash = hashlib.sha256((message or "").encode("utf-8")).hexdigest()
        last_hash = st.get(f"{key}::last_hash")
        if last_hash == new_hash:
            logger("Info", "Telegram status unchanged; skipped edit")
            return
    except Exception:
        pass
    edit_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/editMessageText"
    payload = {
        "chat_id": str(TELEGRAM_CHAT_ID),
        "message_id": mid,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        r = requests.post(edit_url, data=payload, timeout=10)
        if r.status_code == 200:
            try:
                st[f"{key}::last_hash"] = new_hash
                _save_telegram_state(st)
            except Exception:
                pass
            logger("Success", "Telegram status updated")
        else:
            desc = ""
            try:
                js = r.json() or {}
                desc = str(js.get("description", ""))
            except Exception:
                desc = ""
            if "message is not modified" in desc.lower():
                try:
                    st[f"{key}::last_hash"] = new_hash
                    _save_telegram_state(st)
                except Exception:
                    pass
                logger("Info", "Telegram edit skipped: message not modified")
            else:
                st = _load_telegram_state()
                key = _status_key()
                st.pop(key, None)
                _save_telegram_state(st)
                STATUS_MESSAGE_ID = None
                _ensure_status_message(message)
                snippet = ""
                try:
                    snippet = (r.text or "")[:120].replace("\n", " ")
                except Exception:
                    pass
                logger("Warning", f"Edit failed ({r.status_code}). Recreated status message. {snippet}")
    except requests.RequestException:
        logger("Error", "Request error while editing Telegram message.")

def send_telegram_notification(message):
    _tg_send(message)

def _escape_html(s):
    try:
        t = "" if s is None else str(s)
        return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    except Exception:
        return ""

def _format_status_html():
    from telegram_status import format_status_html as _fmt
    return _fmt(STATUS)

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

def update_status(fields=None):
    _tg_update_status(STATUS, fields or {}, gpu_fallback="-")

def update_status_rl(fields, category, min_interval):
    try:
        for k, v in (fields or {}).items():
            STATUS[k] = v
    except Exception:
        pass
    _tg_update_status_rl(STATUS, fields or {}, category, min_interval, gpu_fallback="-")

# ----------------------------------------------------------------------------------------------

LAST_TELEGRAM_TS = {}

def send_telegram_notification_rl(message, category, min_interval):
    _tg_send_rl(message, category, min_interval)

def fetch_block_data():
    """
    Fetch the work block from API and notify via Telegram on failure.
    """
    headers = {"pool-token": POOL_TOKEN, "ngrok-skip-browser-warning": "true", "User-Agent": "unitead-gpu-script/1.0"}
    
    try:
        logger("Info", f"Fetching data from {API_URL}")
        params = {"length": BLOCK_LENGTH} if BLOCK_LENGTH else None
        response = requests.get(API_URL, headers=headers, params=params, timeout=15)
        if response.status_code == 200:
            return response.json()
        if response.status_code == 409:
            try:
                data = response.json()
            except Exception:
                data = {"error": (response.text or "").strip()}
            msg = str(data.get("error", "")).strip()
            if msg.lower() == "all blocks are solved":
                global ALL_BLOCKS_SOLVED
                ALL_BLOCKS_SOLVED = True
                update_status({"all_blocks_solved": True, "next_fetch_in": 0})
                logger("Success", "All blocks solved. Shutting down.")
                return None
            update_status_rl({"last_error": f"No range available: `{msg or 'No available random range'}`"}, "no_range", 300)
            logger("Error", f"Error fetching block: 409 - {response.text}")
            return None
        if 500 <= response.status_code <= 599:
            notify_error("api_offline", f"API offline `{response.status_code}`", api_offline=True, sleep_seconds=0, rate_limit=300)
            return None
        notify_error("api_fetch_error", f"API error `{response.status_code}`", api_offline=False, sleep_seconds=0, rate_limit=300)
        return None
    except requests.RequestException as e:
        notify_error("api_offline", f"API connection error `{type(e).__name__}`", api_offline=True, sleep_seconds=0, rate_limit=300)
        return None

# ----------------------------------------------------------------------------------------------

def post_private_keys(private_keys):
    headers = {
        "pool-token": POOL_TOKEN,
        "Content-Type": "application/json",
        "ngrok-skip-browser-warning": "true",
        "User-Agent": "unitead-gpu-script/1.0"
    }
    data = {"privateKeys": private_keys}
    logger("Info", f"Posting batch of {len(private_keys)} private keys to API.")
    
    try:
        url = API_URL+"/submit"
        response = requests.post(url, headers=headers, json=data, timeout=10)
        if response.status_code == 200:
            logger("Success", "Private keys posted successfully.")
            update_status({"last_batch": f"Sent {len(private_keys)} keys"})
            try:
                _clean_gpu_out_files()
            except Exception:
                pass
            try:
                globals()["POST_ERROR_CONSECUTIVE"] = 0
            except Exception:
                pass
            return (True, False)
        else:
            txt = ""
            try:
                txt = (response.text or "").strip()
            except Exception:
                txt = ""
            msg = txt.lower()
            is_incompatible = (
                ("incompatible privatekeys" in msg) or
                ("incompatible private keys" in msg) or
                ("not all private keys are correct" in msg)
            )
            is_no_target_block = (
                ("no target block found" in msg) or
                ("provide blockid or have an active block" in msg)
            )
            if not is_incompatible:
                try:
                    js = response.json()
                    em = str(js.get("error", "")).lower()
                    if em:
                        is_incompatible = (
                            ("incompatible privatekeys" in em) or
                            ("incompatible private keys" in em) or
                            ("not all private keys are correct" in em)
                        )
                        if not is_no_target_block:
                            is_no_target_block = (
                                ("no target block found" in em) or
                                ("provide blockid or have an active block" in em)
                            )
                except Exception:
                    pass
            if 500 <= response.status_code <= 599:
                snippet = ""
                try:
                    snippet = (response.text or "")[:120].replace("\n", " ")
                except Exception:
                    snippet = ""
                logger("Error", f"Failed to send batch: Status {response.status_code}. Retrying in 30s.")
                if snippet:
                    logger("Info", f"Detail: {snippet}...")
                update_status_rl({"last_batch": f"Server error {response.status_code}", "last_error": f"Post server error `{response.status_code}`"}, "post_server_error", 300)
                notify_error("api_offline", f"Post server error `{response.status_code}`", api_offline=True, sleep_seconds=0, rate_limit=300)
                return (False, False)
            if is_incompatible:
                attempts = 1
                while attempts < 3:
                    try:
                        r2 = requests.post(url, headers=headers, json=data, timeout=10)
                        if r2.status_code == 200:
                            logger("Success", "Private keys posted successfully.")
                            update_status({"last_batch": f"Sent {len(private_keys)} keys"})
                            return (True, False)
                    except requests.RequestException:
                        pass
                    attempts += 1
                update_status_rl({"last_batch": "Incompatible privatekeys"}, "post_incompatible", 300)
                logger("Error", "API reports incompatible privatekeys after 3 attempts.")
                return (False, True)
            snippet = ""
            try:
                snippet = (response.text or "")[:120].replace("\n", " ")
            except Exception:
                snippet = ""
            logger("Error", f"Failed to send batch: Status {response.status_code}. Retrying in 30s.")
            if snippet:
                logger("Info", f"Detail: {snippet}...")
            update_status_rl({"last_batch": f"Failed status {response.status_code}", "last_error": f"Post error `{response.status_code}`"}, "post_error", 300)
            notify_error("post_error", f"Post error `{response.status_code}`", api_offline=False, sleep_seconds=0, rate_limit=300)
            if is_no_target_block:
                try:
                    globals()["POST_ERROR_CONSECUTIVE"] = int(globals().get("POST_ERROR_CONSECUTIVE", 0)) + 1
                except Exception:
                    pass
                try:
                    cnt = int(globals().get("POST_ERROR_CONSECUTIVE", 0))
                    if cnt >= 3:
                        globals()["POST_ERROR_CONSECUTIVE"] = 0
                        try:
                            PENDING_KEYS = []
                            _save_pending_keys()
                        except Exception:
                            pass
                        try:
                            if os.path.exists(PENDING_KEYS_FILE):
                                os.remove(PENDING_KEYS_FILE)
                        except Exception:
                            pass
                        try:
                            clean_io_files()
                        except Exception:
                            pass
                        try:
                            globals()["NEED_NEW_BLOCK_FETCH"] = True
                        except Exception:
                            pass
                        try:
                            send_telegram_notification("Post errors: no active block. Resetting state.")
                        except Exception:
                            pass
                except Exception:
                    pass
            return (False, False)
    except requests.RequestException as e:
        logger("Error", f"Connection error while sending batch: {type(e).__name__}. Retrying in 30s.")
        update_status_rl({"last_batch": f"Connection error {type(e).__name__}", "last_error": f"Post connection error `{type(e).__name__}`"}, "post_network_error", 300)
        notify_error("api_offline", f"Post connection error `{type(e).__name__}`", api_offline=True, sleep_seconds=0, rate_limit=300)
        return (False, False)

# ==============================================================================================
#                                    MAIN WORK FUNCTIONS
# ==============================================================================================
# ... (Funções save_addresses_to_in_file, run_external_program e process_out_file não alteradas)
# ...

# ----------------------------------------------------------------------------------------------

def save_addresses_to_in_file(addresses, additional_addresses):
    all_addresses = list(addresses)
    extras = [a for a in (additional_addresses or []) if isinstance(a, str) and a.strip()]
    for a in extras:
        if a not in all_addresses:
            all_addresses.append(a)

    try:
        with open(IN_FILE, "w") as file:
            file.write("\n".join(all_addresses) + "\n")
        logger("Info", f"Addresses saved to '{IN_FILE}'. Total: {len(all_addresses)}")
    except Exception as e:
        logger("Error", f"Failed to save addresses to '{IN_FILE}': {e}")
        return False

def clean_io_files():
    try:
        with open(IN_FILE, "w"):
            pass
        with open(OUT_FILE, "w"):
            pass
        _clean_gpu_out_files()
    except Exception:
        pass

def clean_out_file():
    try:
        with open(OUT_FILE, "w"):
            pass
    except Exception:
        pass

# ----------------------------------------------------------------------------------------------

def _gpu_out_path(i):
    return f"out_gpu_{i}.txt"

def _clean_gpu_out_files():
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        for name in os.listdir(here):
            try:
                if re.fullmatch(r"out_gpu_\d+\.txt", name):
                    p = os.path.join(here, name)
                    try:
                        os.remove(p)
                    except Exception:
                        try:
                            with open(p, "w"):
                                pass
                        except Exception:
                            pass
            except Exception:
                pass
    except Exception:
        pass

def _split_keyspace(start_hex, end_hex, parts):
    try:
        s = int(str(start_hex), 16)
        e = int(str(end_hex), 16)
        if e <= s or parts <= 1:
            return [(str(start_hex), str(end_hex))]
        length = e - s
        segments = []
        for i in range(parts):
            si = s + (length * i) // parts
            ei = s + (length * (i + 1)) // parts
            if i == parts - 1:
                ei = e
            segments.append((f"{si:x}", f"{ei:x}"))
        return segments
    except Exception:
        return [(str(start_hex), str(end_hex))]

def _combine_gpu_out_files(count):
    try:
        with open(OUT_FILE, "w") as out:
            for i in range(count):
                p = _gpu_out_path(i)
                if os.path.exists(p):
                    try:
                        with open(p, "r") as f:
                            out.write(f.read())
                    except Exception:
                        pass
    except Exception:
        pass

def _stream_gpu_output(proc, gid):
    try:
        for raw in proc.stdout:
            txt = (raw or "").rstrip("\n").strip()
            if txt:
                print(f"{Fore.CYAN}[GPU {gid}] {txt}{Style.RESET_ALL}", flush=True)
    except Exception:
        pass

def _parse_length_to_count(s):
    try:
        if not s:
            return None
        txt = str(s).strip().upper()
        m = re.fullmatch(r"(\d+)([KMBT]?)", txt)
        if not m:
            return None
        val = int(m.group(1))
        unit = m.group(2)
        mult = {
            "K": 10**3,
            "M": 10**6,
            "B": 10**9,
            "T": 10**12,
        }.get(unit, 1)
        return int(val * mult)
    except Exception:
        return None

def run_external_program(start_hex, end_hex):
    """Run external program with given keyspace and stream live feedback."""
    keyspace = f"{start_hex}:{end_hex}"
    clean_out_file()
    _clean_gpu_out_files()
    logger("Info", f"Running with keyspace: {Fore.GREEN}{keyspace}{Style.RESET_ALL}")
    gpu_ids = _detect_gpu_list()
    kind = (PROGRAM_KIND or "").strip().lower()
    if len(gpu_ids) > 1:
        segments = _split_keyspace(start_hex, end_hex, len(gpu_ids))
        procs = []
        threads = []
        first_fail = None
        for idx, gid in enumerate(gpu_ids):
            outp = _gpu_out_path(idx)
            base = [APP_PATH]
            if isinstance(APP_ARGS, str) and APP_ARGS.strip():
                parsed = shlex.split(APP_ARGS)
                filtered = []
                i = 0
                while i < len(parsed):
                    if parsed[i] == "-gpuId" and i + 1 < len(parsed):
                        i += 2
                        continue
                    filtered.append(parsed[i])
                    i += 1
                base += filtered
            args = list(base)
            args += ["-i", IN_FILE, "-o", outp, "--keyspace", f"{segments[idx][0]}:{segments[idx][1]}"]
            if "vanity" in kind:
                args += ["-gpuId", str(gid)]
            try:
                p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
                procs.append(p)
                print(f"{Fore.CYAN}[GPU {gid}] started {segments[idx][0]}:{segments[idx][1]}{Style.RESET_ALL}")
                t = threading.Thread(target=_stream_gpu_output, args=(p, gid), daemon=True)
                t.start()
                threads.append(t)
            except FileNotFoundError:
                logger("Error", "External program not found. Check path and permissions.")
                update_status_rl({"last_error": "Program not found"}, "program_not_found", 120)
                notify_error("program_not_found", "Program not found", api_offline=False, sleep_seconds=0, rate_limit=120)
                return False
            except Exception as e:
                logger("Error", f"Exception while starting GPU {gid}: {e}")
                update_status_rl({"last_error": f"Program start exception `{type(e).__name__}`"}, "program_exception", 120)
                notify_error("program_exception", f"Program start exception `{type(e).__name__}`", api_offline=False, sleep_seconds=0, rate_limit=120)
                return False
        ok_all = True
        for p in procs:
            rc = p.wait()
            if rc != 0:
                ok_all = False
                if first_fail is None:
                    first_fail = rc
        for t in threads:
            try:
                t.join(timeout=1.0)
            except Exception:
                pass
        _combine_gpu_out_files(len(gpu_ids))
        if ok_all:
            try:
                globals()["LAST_RUN_OK"] = True
            except Exception:
                pass
            logger("Success", "External program finished successfully")
            _clean_gpu_out_files()
            return True
        try:
            globals()["LAST_RUN_OK"] = False
        except Exception:
            pass
        logger("Error", f"External program failed with return code: {first_fail if first_fail is not None else -1}")
        update_status_rl({"last_error": f"Program failed code `{first_fail if first_fail is not None else -1}`"}, "program_failed", 120)
        notify_error("program_failed", f"Program failed code `{first_fail if first_fail is not None else -1}`", api_offline=False, sleep_seconds=0, rate_limit=120)
        return False
    selected_gpu = 0
    try:
        env_hint = os.environ.get("CUDA_VISIBLE_DEVICES")
        if env_hint:
            parts = [p.strip() for p in env_hint.split(",") if p.strip()]
            if parts and parts[0].isdigit():
                selected_gpu = int(parts[0])
        elif gpu_ids:
            selected_gpu = int(gpu_ids[0])
        m = re.search(r"-gpuId\s+(\d+)", str(APP_ARGS or ""))
        if m and not env_hint:
            selected_gpu = int(m.group(1))
    except Exception:
        selected_gpu = 0
    base = [APP_PATH]
    if isinstance(APP_ARGS, str) and APP_ARGS.strip():
        base += shlex.split(APP_ARGS)
    if ("vanity" in kind) and not re.search(r"-gpuId\s+\d+", " ".join(base)):
        base += ["-gpuId", "0"]
    command = base + ["-i", IN_FILE, "-o", OUT_FILE, "--keyspace", keyspace]
    try:
        env = os.environ.copy()
        try:
            existing = env.get("CUDA_VISIBLE_DEVICES")
            if existing:
                env["CUDA_VISIBLE_DEVICES"] = existing
            else:
                env["CUDA_VISIBLE_DEVICES"] = str(selected_gpu)
        except Exception:
            pass
        with subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        ) as process:
            last_dyn_len = 0
            progress_re = re.compile(r"^\s*\[\s*\d+(?:\.\d+)?\s*[GMK]?keys/s\].*", re.IGNORECASE)
            for raw in process.stdout:
                msg = raw.rstrip("\n")
                txt = msg.strip()
                if progress_re.match(txt):
                    display = f"{Fore.CYAN}  > {txt}{Style.RESET_ALL}"
                    pad = max(0, last_dyn_len - len(display))
                    sys.stdout.write("\r" + display + (" " * pad))
                    sys.stdout.flush()
                    last_dyn_len = len(display)
                else:
                    if last_dyn_len:
                        sys.stdout.write("\r" + (" " * last_dyn_len) + "\r")
                        sys.stdout.flush()
                        last_dyn_len = 0
                    print(f"{Fore.CYAN}  > {txt}{Style.RESET_ALL}", flush=True)
            if last_dyn_len:
                sys.stdout.write("\n")
                sys.stdout.flush()
            return_code = process.wait()
            if return_code == 0:
                try:
                    globals()["LAST_RUN_OK"] = True
                except Exception:
                    pass
                logger("Success", "External program finished successfully")
                _clean_gpu_out_files()
                return True
            else:
                try:
                    globals()["LAST_RUN_OK"] = False
                except Exception:
                    pass
                logger("Error", f"External program failed with return code: {return_code}")
                update_status_rl({"last_error": f"Program failed code `{return_code}`"}, "program_failed", 120)
                notify_error("program_failed", f"Program failed code `{return_code}`", api_offline=False, sleep_seconds=0, rate_limit=120)
                return False
    except FileNotFoundError:
        try:
            globals()["LAST_RUN_OK"] = False
        except Exception:
            pass
        logger("Error", "External program not found. Check path and permissions.")
        update_status_rl({"last_error": "Program not found"}, "program_not_found", 120)
        notify_error("program_not_found", "Program not found", api_offline=False, sleep_seconds=0, rate_limit=120)
        return False
    except Exception as e:
        try:
            globals()["LAST_RUN_OK"] = False
        except Exception:
            pass
        logger("Error", f"Exception while executing: {e}")
        update_status_rl({"last_error": f"Program exception `{type(e).__name__}`"}, "program_exception", 120)
        notify_error("program_exception", f"Program exception `{type(e).__name__}`", api_offline=False, sleep_seconds=0, rate_limit=120)
        return False

# ----------------------------------------------------------------------------------------------

def process_out_file():
    """
    Process out.txt, check additional address hit, notify via Telegram,
    and enqueue other keys for API posting.
    """
    global PENDING_KEYS
    if not os.path.exists(OUT_FILE):
        logger("Warning", f"File '{OUT_FILE}' not found for processing.")
        update_status_rl({"last_error": f"Output file missing"}, "output_missing", 120)
        notify_error("output_missing", "Output file missing", api_offline=False, sleep_seconds=0, rate_limit=120)
        return False

    keys_to_post = []
    found_pairs = []
    
    try:
        with open(OUT_FILE, "r") as file:
            content = file.read()
        # Prefer explicit PROGRAM_KIND from settings; fall back to app basename
        kind = (PROGRAM_KIND or "").strip().lower()
        if not kind:
            bname = os.path.basename((APP_PATH or "").lower())
            if "bitcrack" in bname:
                kind = "bitcrack"
            elif "vanitysearch-v2" in bname or "vanitysearch-v3" in bname:
                kind = "vanitysearch-v3"
            else:
                kind = "vanity"
        keys_to_post, found_pairs = parse_out(content, kind, ADDITIONAL_ADDRESSES)
    except Exception as e:
        logger("Error", f"Error processing file '{OUT_FILE}': {e}")
        update_status_rl({"last_error": f"Output parse error `{type(e).__name__}`"}, "output_parse_error", 120)
        notify_error("output_parse_error", f"Output parse error `{type(e).__name__}`", api_offline=False, sleep_seconds=0, rate_limit=120)
        return False

    # 1. Check and Save Additional Address hit (and Notify)
    if found_pairs:
        logger("KEYFOUND", f"{len(found_pairs)} key(s) for additional addresses found. Stopping...")
        
        # Save found private key to file
        try:
            with open(KEYFOUND_FILE, "w") as file:
                file.write("\n".join([f"{addr}:{key}" for (addr, key) in found_pairs]) + "\n")
            logger("KEYFOUND", f"Private key saved in '{KEYFOUND_FILE}'.")
        except Exception as e:
            logger("KEYFOUND Error", f"Failed to save private key to file: {e}")
        if SEND_ADDITIONAL_KEYS_TO_API:
            try:
                add_privs = [str(k).replace("0x", "").upper() for (_addr, k) in found_pairs if isinstance(k, str) and k.strip()]
                if add_privs:
                    post_private_keys(add_privs)
            except Exception:
                pass
        if keys_to_post:
            PENDING_KEYS.extend(keys_to_post)
            _save_pending_keys()
        update_status({"keyfound": f"{len(found_pairs)} saved to {KEYFOUND_FILE}", "pending_keys": len(PENDING_KEYS)})
        return True
    
    if keys_to_post:
        PENDING_KEYS.extend(keys_to_post)
        logger("Info", f"Accumulated {len(PENDING_KEYS)} keys for posting.")
        _save_pending_keys()
        update_status({"pending_keys": len(PENDING_KEYS)})

    # 3. Clear out.txt for the next cycle
    try:
        with open(OUT_FILE, "w"):
            pass
        logger("Info", f"File '{OUT_FILE}' cleared for next cycle.")
        _clean_gpu_out_files()
    except Exception as e:
        logger("Error", f"Failed to clear file '{OUT_FILE}': {e}")
        update_status_rl({"last_error": f"Clear out error `{type(e).__name__}`"}, "clear_out_error", 120)
        notify_error("clear_out_error", f"Clear out error `{type(e).__name__}`", api_offline=False, sleep_seconds=0, rate_limit=120)

    return False # Indicates the additional address key was NOT found

# ----------------------------------------------------------------------------------------------

def _pad64_hex(n):
    try:
        h = hex(n)[2:]
        return ("0x" + h.zfill(64))
    except Exception:
        return None

def _generate_filler_keys(count, start_hex, end_hex, exclude=None):
    try:
        exclude_set = set([str(e).lower().replace("0x", "") for e in (exclude or [])])
        start = int(start_hex, 16)
        end = int(end_hex, 16)
        span = end - start
        if span <= 0 or count <= 0:
            return []
        out = []
        attempts = 0
        import secrets
        while len(out) < count and attempts < count * 100:
            rnd = secrets.token_bytes(32)
            rnd_int = int.from_bytes(rnd, "big")
            offset = rnd_int % span
            val = start + offset
            h = hex(val)[2:].zfill(64)
            if h not in exclude_set and h.lower() not in exclude_set and h.upper() not in out:
                out.append(h.upper())
            attempts += 1
        return out
    except Exception:
        return []

# ==============================================================================================
#                                    MAIN LOOP
# ==============================================================================================

if __name__ == "__main__":
    clean_io_files()
    refresh_settings()
    _load_pending_keys()
    STATUS["session_id"] = uuid.uuid4().hex[:8]
    STATUS["session_started_ts"] = time.time()
    STATUS["session_blocks"] = 0
    STATUS["session_consecutive"] = 0
    STATUS["session_keyspace_total"] = 0
    while True:
        try:
            refresh_settings()
            flush_pending_keys_blocking()
            if 'NEED_NEW_BLOCK_FETCH' in globals() and NEED_NEW_BLOCK_FETCH:
                NEED_NEW_BLOCK_FETCH = False
                update_status({"pending_keys": len(PENDING_KEYS), "next_fetch_in": 0})
                logger("Info", "Incompatible keys detected and cleared. Fetching a new block immediately.")
                continue
            if ONE_SHOT and PROCESSED_ONE_BLOCK:
                logger("Info", "One-shot mode enabled. Exiting after first block.")
                break
            block_data = fetch_block_data()
            if ALL_BLOCKS_SOLVED:
                break
            if not block_data:
                logger("Error", "Could not fetch block data. Retrying in 30 seconds.")
                time.sleep(30)
                continue
            addresses = block_data.get("checkwork_addresses", [])
            range_data = block_data.get("range", {})
            start_hex = range_data.get("start", "").replace("0x", "")
            end_hex = range_data.get("end", "").replace("0x", "")
            block_size = 0
            try:
                if start_hex and end_hex:
                    block_size = int(end_hex, 16) - int(start_hex, 16)
            except Exception:
                block_size = 0
            current_keyspace = f"{start_hex}:{end_hex}"
            if not addresses:
                notify_error("no_addresses", "No addresses in block", api_offline=False, sleep_seconds=30, rate_limit=120)
                continue
            if not (start_hex and end_hex):
                notify_error("missing_key_range", "Key range missing", api_offline=False, sleep_seconds=30, rate_limit=120)
                continue
            if current_keyspace != previous_keyspace:
                previous_keyspace = current_keyspace
                gpu_labels = _detect_gpu_labels()
                if gpu_labels:
                    gpu_label = "\n" + "\n".join(gpu_labels)
                else:
                    gpu_label = _detect_gpu_label()
                algo_label = _program_label()
                update_status({"range": current_keyspace, "addresses": len(addresses), "gpu": gpu_label, "algorithm": algo_label, "arguments": _status_program_args()})
                logger("Info", f"New block notification sent: {current_keyspace}")
            try:
                CURRENT_ADDR_COUNT = int(len(addresses) or 10)
                CURRENT_RANGE_START = start_hex
                CURRENT_RANGE_END = end_hex
            except Exception:
                pass
            save_addresses_to_in_file(addresses, ADDITIONAL_ADDRESSES)
            ran_ok = run_external_program(start_hex, end_hex)
            solution_found = process_out_file()
            if ran_ok:
                STATUS["session_blocks"] = int(STATUS.get("session_blocks", 0)) + 1
                STATUS["session_consecutive"] = int(STATUS.get("session_consecutive", 0)) + 1
                try:
                    STATUS["session_keyspace_total"] = int(STATUS.get("session_keyspace_total", 0)) + int(block_size)
                except Exception:
                    pass
            else:
                STATUS["session_consecutive"] = 0
            PROCESSED_ONE_BLOCK = True
            if solution_found:
                logger("Success", "ADDITIONAL ADDRESS KEY FOUND. Exiting script.")
                break
            flush_pending_keys_blocking()
            if 'NEED_NEW_BLOCK_FETCH' in globals() and NEED_NEW_BLOCK_FETCH:
                NEED_NEW_BLOCK_FETCH = False
                update_status({"pending_keys": len(PENDING_KEYS), "next_fetch_in": 0})
                logger("Info", "Incompatible keys detected and cleared. Fetching a new block immediately.")
                continue
            if ONE_SHOT:
                logger("Info", "One-shot mode enabled. Exiting after first block.")
                break
            update_status({"pending_keys": len(PENDING_KEYS), "next_fetch_in": POST_BLOCK_DELAY_SECONDS})
            logger("Info", f"No critical solution this round. Waiting {POST_BLOCK_DELAY_SECONDS} seconds for next fetch.")
            time.sleep(POST_BLOCK_DELAY_SECONDS)
        except Exception as e:
            try:
                update_status_rl({"last_error": f"Main loop exception `{type(e).__name__}`"}, "main_loop_exception", 120)
            except Exception:
                pass
            try:
                logger("Error", f"Unhandled error in main loop: {e}")
            except Exception:
                pass
            try:
                PENDING_KEYS = []
                _save_pending_keys()
            except Exception:
                pass
            try:
                if os.path.exists(PENDING_KEYS_FILE):
                    os.remove(PENDING_KEYS_FILE)
            except Exception:
                pass
            try:
                clean_io_files()
            except Exception:
                pass
            try:
                globals()["NEED_NEW_BLOCK_FETCH"] = True
            except Exception:
                pass
            try:
                time.sleep(5)
            except Exception:
                pass
            continue
