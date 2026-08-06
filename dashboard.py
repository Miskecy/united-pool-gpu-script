#!/usr/bin/env python3
"""
Web dashboard for the GPU miner.
  python3 dashboard.py
Access at http://YOUR_VPS_IP:<port> — reads dashboard_port from settings.json.
Set "dashboard_password" in settings.json to require a login.
"""
import glob
import json
import os
import signal
import threading
import time
import subprocess
import functools

from flask import Flask, render_template, jsonify, Response, request, abort

SCRIPT_DIR        = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, template_folder=os.path.join(SCRIPT_DIR, "templates"))

@app.after_request
def _no_cache(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response

LOG_FILE          = os.path.join(SCRIPT_DIR, "miner.log")
STATUS_FILE       = os.path.join(SCRIPT_DIR, "status.json")
SETTINGS_FILE     = os.path.join(SCRIPT_DIR, "settings.json")
PID_FILE          = os.path.join(SCRIPT_DIR, ".miner.pid")
DASHBOARD_PID_FILE= os.path.join(SCRIPT_DIR, ".dashboard.pid")
MINER_SH          = os.path.join(SCRIPT_DIR, "miner.sh")
IN_FILE           = os.path.join(SCRIPT_DIR, "in.txt")
OUT_FILE          = os.path.join(SCRIPT_DIR, "out.txt")
PENDING_KEYS_FILE = os.path.join(SCRIPT_DIR, "pending_keys.json")
STOP_FLAG_FILE    = os.path.join(SCRIPT_DIR, ".stop_after_block")


def _load_settings():
    with open(SETTINGS_FILE, encoding="utf-8") as f:
        return json.load(f)


def _save_settings(data):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


def _get_password():
    try:
        return str(_load_settings().get("dashboard_password", ""))
    except Exception:
        return ""


def _get_port():
    try:
        return int(_load_settings().get("dashboard_port", 8080))
    except Exception:
        return int(os.environ.get("DASHBOARD_PORT", 8080))


def _miner_pid():
    try:
        if os.path.exists(PID_FILE):
            pid = int(open(PID_FILE).read().strip())
            os.kill(pid, 0)  # signal 0 = alive check
            return pid
    except Exception:
        pass
    return None


def _require_auth(f):
    @functools.wraps(f)
    def wrapped(*args, **kwargs):
        pwd = _get_password()
        if pwd:
            auth = request.authorization
            if not auth or auth.password != pwd:
                return Response(
                    "Authentication required",
                    401,
                    {"WWW-Authenticate": 'Basic realm="GPU Miner Dashboard"'},
                )
        return f(*args, **kwargs)
    return wrapped


@app.route("/")
@_require_auth
def index():
    return render_template("index.html")


@app.route("/api/status")
@_require_auth
def api_status():
    data = {}
    try:
        if os.path.exists(STATUS_FILE):
            with open(STATUS_FILE, encoding="utf-8") as f:
                data = json.load(f)
    except Exception:
        pass
    pid = _miner_pid()
    data["miner_running"] = pid is not None
    data["miner_pid"] = pid or ""
    data["graceful_stop_pending"] = os.path.exists(STOP_FLAG_FILE)
    return jsonify(data)


@app.route("/api/logs/poll")
@_require_auth
def log_poll():
    offset = request.args.get("offset", type=int, default=-1)
    try:
        if not os.path.exists(LOG_FILE):
            return jsonify({"lines": [], "offset": 0})
        with open(LOG_FILE, "rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            if offset < 0:
                start = max(0, size - 10240)   # initial load: last 10 KB
            elif offset > size:
                start = 0                       # file was rotated/truncated
            else:
                start = offset
            if start >= size:
                return jsonify({"lines": [], "offset": size})
            fh.seek(start)
            chunk = fh.read(min(size - start, 65536))
        text = chunk.decode("utf-8", errors="replace")
        lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
        return jsonify({"lines": lines, "offset": start + len(chunk)})
    except Exception:
        return jsonify({"lines": [], "offset": max(0, offset or 0)})


@app.route("/api/miner/<action>", methods=["POST"])
@_require_auth
def miner_ctrl(action):
    # Map dashboard actions to miner.sh commands
    ACTION_MAP = {
        "start":   "start-miner",
        "stop":    "stop-miner",
        "restart": "restart-miner",
    }

    if action == "stop-graceful":
        try:
            open(STOP_FLAG_FILE, "w").close()
            return jsonify({"ok": True, "out": "Graceful stop flag set. Miner will stop after current block."})
        except Exception as e:
            return jsonify({"ok": False, "out": str(e)}), 500

    if action == "cancel-graceful":
        try:
            if os.path.exists(STOP_FLAG_FILE):
                os.remove(STOP_FLAG_FILE)
            return jsonify({"ok": True, "out": "Graceful stop cancelled."})
        except Exception as e:
            return jsonify({"ok": False, "out": str(e)}), 500

    if action == "stop-all":
        def _kill_all():
            time.sleep(0.8)
            # Kill miner
            try:
                if os.path.exists(PID_FILE):
                    pid = int(open(PID_FILE).read().strip())
                    os.kill(pid, signal.SIGTERM)
            except Exception:
                pass
            time.sleep(1.5)
            # Kill dashboard (self)
            os.kill(os.getpid(), signal.SIGTERM)

        threading.Thread(target=_kill_all, daemon=True).start()
        return jsonify({"ok": True, "out": "Stopping all processes..."})

    sh_action = ACTION_MAP.get(action)
    if not sh_action:
        abort(400)
    if not os.path.exists(MINER_SH):
        return jsonify({"ok": False, "out": "miner.sh not found"}), 500
    try:
        r = subprocess.run(
            ["bash", MINER_SH, sh_action],
            capture_output=True, text=True, timeout=20,
        )
        return jsonify({"ok": r.returncode == 0, "out": (r.stdout + r.stderr).strip()})
    except Exception as e:
        return jsonify({"ok": False, "out": str(e)}), 500


@app.route("/api/files")
@_require_auth
def api_files():
    result = {}

    for key, path in [("in", IN_FILE), ("out", OUT_FILE)]:
        try:
            if os.path.exists(path):
                with open(path, encoding="utf-8", errors="replace") as f:
                    content = f.read().strip()
                if content:
                    result[key] = content
        except Exception:
            pass

    # During a multi-GPU run out.txt is empty; fall back to per-GPU files
    if "out" not in result:
        try:
            parts = []
            for gf in sorted(glob.glob(os.path.join(SCRIPT_DIR, "out_gpu_*.txt"))):
                with open(gf, encoding="utf-8", errors="replace") as f:
                    c = f.read().strip()
                if c:
                    parts.append(c)
            if parts:
                result["out"] = "\n".join(parts)
        except Exception:
            pass

    try:
        if os.path.exists(PENDING_KEYS_FILE):
            with open(PENDING_KEYS_FILE, encoding="utf-8") as f:
                keys = json.load(f)
            if isinstance(keys, list) and keys:
                result["pending_keys"] = keys
    except Exception:
        pass

    return jsonify(result)


@app.route("/api/settings/telegram", methods=["POST"])
@_require_auth
def toggle_telegram():
    try:
        s = _load_settings()
        current = bool(s.get("telegram_share", True))
        s["telegram_share"] = not current
        _save_settings(s)
        return jsonify({"ok": True, "telegram_share": s["telegram_share"]})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


if __name__ == "__main__":
    port = _get_port()
    pwd = _get_password()
    print(f"\n  ⚡ GPU Miner Dashboard  →  http://0.0.0.0:{port}")
    print(f"  Password protection : {'enabled' if pwd else 'disabled (set dashboard_password in settings.json)'}\n")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
