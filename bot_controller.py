import os
import sys
import time
import json
import requests
import subprocess
import atexit
import signal

BOT_TOKEN = ""
ALLOWED_CHAT_ID = ""
WORKER_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "script.py")
PYTHON_EXEC = sys.executable
SERVER_NAME = ""
TARGET_NAME = None

worker_process = None
_KNOWN_SERVERS = set()

def _load_settings():
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(here, "settings.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f) or {}
    except Exception:
        pass
    return {}

def _apply_settings(s):
    global BOT_TOKEN, ALLOWED_CHAT_ID, SERVER_NAME
    try:
        BOT_TOKEN = os.environ.get("BOT_TOKEN") or s.get("telegram_accesstoken", "")
        ALLOWED_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID") or str(s.get("telegram_chatid", ""))
    except Exception:
        BOT_TOKEN = BOT_TOKEN or ""
        ALLOWED_CHAT_ID = ALLOWED_CHAT_ID or ""
    name = os.environ.get("SERVER_NAME") or s.get("worker_name") or ""
    if not name:
        name = os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or ""
    SERVER_NAME = str(name or "").strip()

def _send(chat_id, text):
    try:
        if not BOT_TOKEN:
            return
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {"chat_id": str(chat_id), "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
        try:
            requests.post(url, data=payload, timeout=10)
        except requests.RequestException:
            pass
    except Exception:
        pass

def _safe_stop_worker():
    global worker_process
    try:
        if worker_process is None:
            return
        pid = worker_process.pid
        if os.name == "posix":
            try:
                os.killpg(os.getpgid(pid), 9)
            except Exception:
                try:
                    worker_process.kill()
                except Exception:
                    pass
        else:
            try:
                worker_process.terminate()
                worker_process.wait(timeout=3)
            except Exception:
                try:
                    worker_process.kill()
                except Exception:
                    pass
        worker_process = None
    except Exception:
        pass

def get_worker_status():
    global worker_process
    if worker_process is None:
        return "🔴 Inactive"
    try:
        if worker_process.poll() is None:
            return f"🟢 Running (PID: {worker_process.pid})"
        code = worker_process.returncode
        worker_process = None
        return f"🔴 Terminated (code {code})"
    except Exception:
        worker_process = None
        return "🔴 Unknown"

def _should_execute(chat_id, explicit_target=None):
    if str(chat_id) != str(ALLOWED_CHAT_ID):
        return False
    t = explicit_target if explicit_target else TARGET_NAME
    if t:
        if not SERVER_NAME:
            return False
        return str(SERVER_NAME).lower() == str(t).lower()
    return True

def start_worker(chat_id, explicit_target=None):
    global worker_process
    if not _should_execute(chat_id, explicit_target):
        return
    status = get_worker_status()
    if status.startswith("🟢"):
        _send(chat_id, f"❌ Already running. {status}")
        return
    try:
        log_out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "worker_stdout.log")
        log_err_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "worker_stderr.log")
        out_f = open(log_out_path, "a", buffering=1)
        err_f = open(log_err_path, "a", buffering=1)
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" and hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP") else 0
        worker_process = subprocess.Popen(
            [PYTHON_EXEC, WORKER_SCRIPT],
            stdout=out_f,
            stderr=err_f,
            creationflags=flags,
        )
        _send(chat_id, f"✅ Started. PID: {worker_process.pid}")
    except Exception as e:
        worker_process = None
        _send(chat_id, f"❌ Error starting: {type(e).__name__}")

def stop_worker(chat_id, explicit_target=None):
    global worker_process
    if not _should_execute(chat_id, explicit_target):
        return
    status = get_worker_status()
    if worker_process is None:
        _send(chat_id, f"❌ Already inactive. {status}")
        return
    try:
        pid = worker_process.pid
        if os.name == "posix":
            try:
                os.killpg(os.getpgid(pid), 9)
            except Exception:
                try:
                    worker_process.kill()
                except Exception:
                    pass
        else:
            try:
                worker_process.terminate()
                worker_process.wait(timeout=5)
            except Exception:
                try:
                    worker_process.kill()
                except Exception:
                    pass
        worker_process = None
        _send(chat_id, f"✅ Stopped. PID: {pid}")
    except Exception as e:
        _send(chat_id, f"❌ Error stopping: {type(e).__name__}")

def restart_worker(chat_id, explicit_target=None):
    if not _should_execute(chat_id, explicit_target):
        return
    _send(chat_id, "🔄 Restarting...")
    stop_worker(chat_id, explicit_target)
    time.sleep(2)
    start_worker(chat_id, explicit_target)

def status_worker(chat_id, explicit_target=None):
    if not _should_execute(chat_id, explicit_target):
        return
    sname = SERVER_NAME or "-"
    tgt = TARGET_NAME or "*"
    _send(chat_id, f"📊 Status: {get_worker_status()} | server: {sname} | target: {tgt}")

def whoami(chat_id):
    if str(chat_id) != str(ALLOWED_CHAT_ID):
        return
    sname = SERVER_NAME or "-"
    _send(chat_id, f"👤 Server: {sname}")

def announce_alive(chat_id):
    try:
        name = SERVER_NAME or "-"
        _KNOWN_SERVERS.add(name)
        _send(chat_id, f"🟢 Server Alive: {name}")
    except Exception:
        pass

def server_list(chat_id):
    try:
        seen = set(_KNOWN_SERVERS)
        deadline = time.time() + 5
        while time.time() < deadline:
            updates = _get_updates(None, timeout=1)
            for u in updates:
                msg = u.get("message") or {}
                txt = (msg.get("text") or "").strip()
                if txt.startswith("🟢 Server Alive:") or txt.startswith("🤝 Server Online:"):
                    try:
                        name = txt.split(":", 1)[1].strip()
                    except Exception:
                        name = txt
                    if name:
                        seen.add(name)
        if not seen:
            _send(chat_id, "📡 No servers discovered.")
            return
        lst = "\n".join([f"• <code>{n}</code>" for n in sorted(seen)])
        _send(chat_id, f"📡 <b>Servers Available</b>\n{lst}")
    except Exception:
        _send(chat_id, "❌ Failed to list servers")

def set_target(chat_id, name):
    global TARGET_NAME
    if str(chat_id) != str(ALLOWED_CHAT_ID):
        return
    if name:
        TARGET_NAME = str(name).strip()
        _send(chat_id, f"🎯 Target set: {TARGET_NAME}")
    else:
        TARGET_NAME = None
        _send(chat_id, "🎯 Target cleared")

def clear_target(chat_id):
    set_target(chat_id, None)

def reload_settings(chat_id):
    if str(chat_id) != str(ALLOWED_CHAT_ID):
        return
    _apply_settings(_load_settings())
    _send(chat_id, "♻️ Settings reloaded")

def get_setting(chat_id, key):
    if str(chat_id) != str(ALLOWED_CHAT_ID):
        return
    s = _load_settings()
    val = s.get(key)
    try:
        txt = json.dumps(val)
    except Exception:
        txt = str(val)
    _send(chat_id, f"🔧 {key} = {txt}")

def set_setting(chat_id, key, raw_value):
    if str(chat_id) != str(ALLOWED_CHAT_ID):
        return
    s = _load_settings()
    vtxt = raw_value.strip()
    parsed = None
    try:
        if vtxt.lower() in ("true", "false"):
            parsed = vtxt.lower() == "true"
        else:
            if vtxt.startswith("[") or vtxt.startswith("{"):
                parsed = json.loads(vtxt)
            else:
                if vtxt.isdigit():
                    parsed = int(vtxt)
                else:
                    try:
                        parsed = float(vtxt)
                    except Exception:
                        parsed = vtxt
    except Exception:
        parsed = vtxt
    s[key] = parsed
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(here, "settings.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(s, f, indent=4)
        _send(chat_id, f"✅ Updated {key}")
    except Exception:
        _send(chat_id, f"❌ Failed to update {key}")

SETTINGS_DESCRIPTIONS = {
    "api_url": "API base URL for block fetch and submit",
    "user_token": "Pool token for worker authentication",
    "worker_name": "Human-readable server/worker name",
    "program_name": "Program identifier (e.g., VanitySearch)",
    "program_path": "Executable path for the cracking program",
    "program_arguments": "CLI arguments passed to the program",
    "block_length": "Keyspace block length (e.g., 1T)",
    "oneshot": "Run a single block and exit (true/false)",
    "post_block_delay_enabled": "Enable delay between blocks",
    "post_block_delay_minutes": "Delay minutes between blocks",
    "additional_addresses": "List of extra target addresses",
    "telegram_share": "Enable Telegram status sharing",
    "telegram_accesstoken": "Telegram bot token",
    "telegram_chatid": "Telegram chat ID",
}

def _format_help():
    s = _load_settings()
    keys = list(s.keys())
    lines = []
    lines.append("🛠️ <b>Bot Controller Help</b>")
    lines.append("")
    lines.append("<b>Targeting</b>")
    lines.append("• <b>/server</b> <i>&lt;name&gt;</i> — set target server name")
    lines.append("• <b>/cleartarget</b> — clear target; commands broadcast")
    lines.append("")
    lines.append("<b>Worker Control</b>")
    lines.append("• <b>/startscript</b> <i>[name]</i> — start worker on target")
    lines.append("• <b>/stopscript</b> <i>[name]</i> — stop worker on target")
    lines.append("• <b>/restartscript</b> <i>[name]</i> — restart worker on target")
    lines.append("• <b>/status</b> <i>[name]</i> — show local status")
    lines.append("• <b>/whoami</b> — show local server name")
    lines.append("")
    lines.append("<b>Settings</b>")
    lines.append("• <b>/get</b> <i>&lt;key&gt;</i> — show current value")
    lines.append("• <b>/set</b> <i>&lt;key&gt; &lt;value&gt;</i> — update value")
    lines.append("  <i>Value parsing</i>: <code>true/false</code> → boolean, numbers → numeric, JSON → lists/objects")
    lines.append("• <b>/reloadsettings</b> — reload settings.json")
    lines.append("")
    lines.append("<b>Available Keys</b>")
    for k in sorted(keys):
        desc = SETTINGS_DESCRIPTIONS.get(k, "custom/unknown key")
        lines.append(f"• <code>{k}</code> — <i>{desc}</i>")
    return "\n".join(lines)

def _get_updates(offset, timeout):
    if not BOT_TOKEN:
        return []
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    params = {"timeout": int(timeout)}
    if offset is not None:
        params["offset"] = int(offset)
    try:
        r = requests.get(url, params=params, timeout=timeout + 5)
        if r.status_code == 200:
            js = {}
            try:
                js = r.json() or {}
            except Exception:
                js = {}
            return js.get("result", [])
    except requests.RequestException:
        return []
    return []

def _handle_update(u):
    try:
        msg = u.get("message") or {}
        chat = msg.get("chat") or {}
        chat_id = chat.get("id")
        text = msg.get("text") or ""
        if not text:
            return
        if str(chat_id) != str(ALLOWED_CHAT_ID):
            return
        t = text.strip()
        low = t.lower()
        parts = t.split()
        arg = parts[1] if len(parts) > 1 else None
        if low.startswith("/startscript"):
            start_worker(chat_id, arg)
        elif low.startswith("/stopscript"):
            stop_worker(chat_id, arg)
        elif low.startswith("/restartscript"):
            restart_worker(chat_id, arg)
        elif low.startswith("/status"):
            status_worker(chat_id, arg)
        elif low.startswith("/server"):
            set_target(chat_id, arg)
        elif low.startswith("/cleartarget"):
            clear_target(chat_id)
        elif low.startswith("/serverlist"):
            announce_alive(chat_id)
            server_list(chat_id)
        elif low.startswith("/reloadsettings"):
            reload_settings(chat_id)
        elif low.startswith("/get ") and arg:
            get_setting(chat_id, arg)
        elif low.startswith("/set ") and len(parts) > 2:
            key = parts[1]
            value = t[t.lower().find(key.lower()) + len(key):].strip()
            set_setting(chat_id, key, value)
        elif low.startswith("/whoami"):
            whoami(chat_id)
        elif low.startswith("/help"):
            _send(chat_id, _format_help())
    except Exception:
        pass

def main():
    _apply_settings(_load_settings())
    if not BOT_TOKEN or not ALLOWED_CHAT_ID:
        print("Error: set telegram_accesstoken and telegram_chatid in settings.json", flush=True)
        sys.exit(1)
    print("Bot Controller started. Running polling...", flush=True)
    atexit.register(_safe_stop_worker)
    try:
        signal.signal(signal.SIGINT, lambda *a: (_safe_stop_worker(), sys.exit(0)))
    except Exception:
        pass
    try:
        signal.signal(getattr(signal, "SIGTERM", signal.SIGINT), lambda *a: (_safe_stop_worker(), sys.exit(0)))
    except Exception:
        pass
    try:
        if os.name == "nt" and hasattr(signal, "SIGBREAK"):
            signal.signal(signal.SIGBREAK, lambda *a: (_safe_stop_worker(), sys.exit(0)))
    except Exception:
        pass
    offset = None
    try:
        _send(ALLOWED_CHAT_ID, f"🤝 Server Online: {SERVER_NAME or '-'}")
        _KNOWN_SERVERS.add(SERVER_NAME or "-")
    except Exception:
        pass
    while True:
        updates = _get_updates(offset, timeout=25)
        for u in updates:
            try:
                offset = int(u.get("update_id", 0)) + 1
            except Exception:
                pass
            _handle_update(u)
        time.sleep(1)

if __name__ == "__main__":
    main()
