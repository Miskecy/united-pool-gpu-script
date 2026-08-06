#!/bin/bash
# miner.sh — manage script.py and dashboard.py as background processes
# Usage: ./miner.sh {start|stop|restart|status|logs|dlogs}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Use venv python if available, otherwise fall back to system python3
VENV_PYTHON="$SCRIPT_DIR/.venv/bin/python3"
PYTHON="$( [ -f "$VENV_PYTHON" ] && echo "$VENV_PYTHON" || echo "python3" )"
MAIN="$SCRIPT_DIR/script.py"
DASHBOARD="$SCRIPT_DIR/dashboard.py"
PID_FILE="$SCRIPT_DIR/.miner.pid"
DASHBOARD_PID_FILE="$SCRIPT_DIR/.dashboard.pid"
LOG_FILE="$SCRIPT_DIR/miner.log"
DASHBOARD_LOG_FILE="$SCRIPT_DIR/dashboard.log"
CLOUDFLARED="$SCRIPT_DIR/cloudflared"
TUNNEL_PID_FILE="$SCRIPT_DIR/.tunnel.pid"
TUNNEL_LOG_FILE="$SCRIPT_DIR/tunnel.log"
TUNNEL_URL_FILE="$SCRIPT_DIR/.tunnel_url"

# ─── helpers ─────────────────────────────────────────────────────────────────

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; BLUE='\033[0;34m'; NC='\033[0m'

_get_dashboard_port() {
    local settings="$SCRIPT_DIR/settings.json"
    [ ! -f "$settings" ] && settings="$SCRIPT_DIR/settings_model.json"
    if [ -f "$settings" ] && command -v python3 &>/dev/null; then
        python3 -c "import json,sys; d=json.load(open('$settings')); print(d.get('dashboard_port',8080))" 2>/dev/null || echo 8080
    else
        echo 8080
    fi
}

_pid_running() {
    local pid="$1"
    [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

_read_pid() {
    [[ -f "$1" ]] && cat "$1" 2>/dev/null || echo ""
}

# ─── miner ───────────────────────────────────────────────────────────────────

_start_miner() {
    local pid
    pid=$(_read_pid "$PID_FILE")
    if _pid_running "$pid"; then
        echo -e "${YELLOW}  [MINER]${NC} Already running — PID $pid. Use 'restart' to reload."
        return 1
    fi
    nohup "$PYTHON" -u "$MAIN" >> "$LOG_FILE" 2>&1 &
    pid=$!
    echo "$pid" > "$PID_FILE"
    sleep 1
    if _pid_running "$pid"; then
        echo -e "${GREEN}  [MINER]${NC} Started — PID $pid"
        echo -e "          Log : tail -f $LOG_FILE"
    else
        echo -e "${RED}  [MINER]${NC} Process exited immediately. Check the log:"
        tail -20 "$LOG_FILE"
        rm -f "$PID_FILE"
        return 1
    fi
}

_stop_miner() {
    local pid waited=0
    pid=$(_read_pid "$PID_FILE")
    if ! _pid_running "$pid"; then
        echo -e "${YELLOW}  [MINER]${NC} Not running."
        rm -f "$PID_FILE"
        return 0
    fi
    echo -e "${CYAN}  [MINER]${NC} Stopping PID $pid..."
    kill "$pid" 2>/dev/null
    while _pid_running "$pid" && (( waited < 10 )); do sleep 1; (( waited++ )); done
    if _pid_running "$pid"; then
        echo -e "${YELLOW}  [MINER]${NC} Did not exit cleanly — sending SIGKILL..."
        kill -9 "$pid" 2>/dev/null
    fi
    rm -f "$PID_FILE"
    echo -e "${GREEN}  [MINER]${NC} Stopped."
}

_status_miner() {
    local pid
    pid=$(_read_pid "$PID_FILE")
    if _pid_running "$pid"; then
        echo -e "${GREEN}  [MINER]${NC} RUNNING — PID $pid  uptime: $(ps -o etime= -p "$pid" 2>/dev/null | tr -d ' ')"
    else
        echo -e "${RED}  [MINER]${NC} STOPPED"
        [[ -f "$PID_FILE" ]] && rm -f "$PID_FILE"
    fi
}

# ─── dashboard ───────────────────────────────────────────────────────────────

_start_dashboard() {
    local pid
    pid=$(_read_pid "$DASHBOARD_PID_FILE")
    if _pid_running "$pid"; then
        echo -e "${YELLOW}  [DASH]${NC}  Already running — PID $pid."
        return 1
    fi
    if [ ! -f "$DASHBOARD" ]; then
        echo -e "${YELLOW}  [DASH]${NC}  dashboard.py not found — skipping."
        return 1
    fi
    nohup "$PYTHON" -u "$DASHBOARD" >> "$DASHBOARD_LOG_FILE" 2>&1 &
    pid=$!
    echo "$pid" > "$DASHBOARD_PID_FILE"
    sleep 1
    if _pid_running "$pid"; then
        echo -e "${GREEN}  [DASH]${NC}  Started — PID $pid"
        echo -e "          Log : tail -f $DASHBOARD_LOG_FILE"
    else
        echo -e "${RED}  [DASH]${NC}  Dashboard exited immediately. Check the log:"
        tail -10 "$DASHBOARD_LOG_FILE"
        rm -f "$DASHBOARD_PID_FILE"
        return 1
    fi
}

_stop_dashboard() {
    local pid waited=0
    pid=$(_read_pid "$DASHBOARD_PID_FILE")
    if ! _pid_running "$pid"; then
        echo -e "${YELLOW}  [DASH]${NC}  Not running."
        rm -f "$DASHBOARD_PID_FILE"
        return 0
    fi
    echo -e "${CYAN}  [DASH]${NC}  Stopping PID $pid..."
    kill "$pid" 2>/dev/null
    while _pid_running "$pid" && (( waited < 10 )); do sleep 1; (( waited++ )); done
    if _pid_running "$pid"; then kill -9 "$pid" 2>/dev/null; fi
    rm -f "$DASHBOARD_PID_FILE"
    echo -e "${GREEN}  [DASH]${NC}  Stopped."
}

_status_dashboard() {
    local pid
    pid=$(_read_pid "$DASHBOARD_PID_FILE")
    if _pid_running "$pid"; then
        echo -e "${GREEN}  [DASH]${NC}  RUNNING — PID $pid  uptime: $(ps -o etime= -p "$pid" 2>/dev/null | tr -d ' ')"
    else
        echo -e "${RED}  [DASH]${NC}  STOPPED"
        [[ -f "$DASHBOARD_PID_FILE" ]] && rm -f "$DASHBOARD_PID_FILE"
    fi
}

# ─── cloudflare tunnel ───────────────────────────────────────────────────────

_start_tunnel() {
    local pid
    pid=$(_read_pid "$TUNNEL_PID_FILE")
    if _pid_running "$pid"; then
        echo -e "${YELLOW}  [TUNNEL]${NC} Already running — PID $pid."
        [ -f "$TUNNEL_URL_FILE" ] && echo -e "           URL : $(cat "$TUNNEL_URL_FILE")"
        return 1
    fi
    if [ ! -f "$CLOUDFLARED" ]; then
        echo -e "${YELLOW}  [TUNNEL]${NC} cloudflared not found — run bash miner_setup.sh first."
        return 1
    fi
    local port
    port=$(_get_dashboard_port)
    rm -f "$TUNNEL_URL_FILE" "$TUNNEL_LOG_FILE"
    nohup "$CLOUDFLARED" tunnel --url "http://localhost:$port" --no-autoupdate >> "$TUNNEL_LOG_FILE" 2>&1 &
    pid=$!
    echo "$pid" > "$TUNNEL_PID_FILE"
    echo -e "${CYAN}  [TUNNEL]${NC} Starting (PID $pid), waiting for URL..."
    local waited=0
    while [ $waited -lt 20 ]; do
        local url
        url=$(grep -oP 'https://\S+\.trycloudflare\.com' "$TUNNEL_LOG_FILE" 2>/dev/null | head -1)
        if [ -n "$url" ]; then
            echo "$url" > "$TUNNEL_URL_FILE"
            echo -e "${GREEN}  [TUNNEL]${NC} Ready — PID $pid"
            echo -e "           URL : ${BLUE}$url${NC}"
            return 0
        fi
        sleep 1
        (( waited++ ))
    done
    if _pid_running "$pid"; then
        echo -e "${YELLOW}  [TUNNEL]${NC} Running but URL not captured yet — check: tail -f $TUNNEL_LOG_FILE"
    else
        echo -e "${RED}  [TUNNEL]${NC} Failed to start. Check: tail -f $TUNNEL_LOG_FILE"
        rm -f "$TUNNEL_PID_FILE"
        return 1
    fi
}

_stop_tunnel() {
    local pid waited=0
    pid=$(_read_pid "$TUNNEL_PID_FILE")
    if ! _pid_running "$pid"; then
        echo -e "${YELLOW}  [TUNNEL]${NC} Not running."
        rm -f "$TUNNEL_PID_FILE" "$TUNNEL_URL_FILE"
        return 0
    fi
    echo -e "${CYAN}  [TUNNEL]${NC} Stopping PID $pid..."
    kill "$pid" 2>/dev/null
    while _pid_running "$pid" && (( waited < 8 )); do sleep 1; (( waited++ )); done
    if _pid_running "$pid"; then kill -9 "$pid" 2>/dev/null; fi
    rm -f "$TUNNEL_PID_FILE" "$TUNNEL_URL_FILE"
    echo -e "${GREEN}  [TUNNEL]${NC} Stopped."
}

_status_tunnel() {
    local pid
    pid=$(_read_pid "$TUNNEL_PID_FILE")
    if _pid_running "$pid"; then
        local url=""
        [ -f "$TUNNEL_URL_FILE" ] && url=$(cat "$TUNNEL_URL_FILE")
        echo -e "${GREEN}  [TUNNEL]${NC} RUNNING — PID $pid  uptime: $(ps -o etime= -p "$pid" 2>/dev/null | tr -d ' ')"
        [ -n "$url" ] && echo -e "           URL : ${BLUE}$url${NC}"
    else
        echo -e "${RED}  [TUNNEL]${NC} STOPPED"
        [[ -f "$TUNNEL_PID_FILE" ]] && rm -f "$TUNNEL_PID_FILE"
    fi
}

# ─── commands ────────────────────────────────────────────────────────────────

cmd_start() {
    echo -e "${CYAN}[START]${NC} Launching miner + dashboard + tunnel..."
    _start_miner
    _start_dashboard
    _start_tunnel
}

cmd_stop() {
    echo -e "${CYAN}[STOP]${NC} Stopping miner + dashboard + tunnel..."
    _stop_miner
    _stop_dashboard
    _stop_tunnel
}

cmd_restart() {
    echo -e "${CYAN}[RESTART]${NC} Restarting miner + dashboard + tunnel..."
    _stop_miner
    _stop_dashboard
    _stop_tunnel
    sleep 1
    _start_miner
    _start_dashboard
    _start_tunnel
}

# ─── miner-only commands (dashboard keeps running) ───────────────

cmd_start_miner() {
    echo -e "${CYAN}[START-MINER]${NC} Launching miner only..."
    _start_miner
}

cmd_stop_miner() {
    echo -e "${CYAN}[STOP-MINER]${NC} Stopping miner only..."
    _stop_miner
}

cmd_restart_miner() {
    echo -e "${CYAN}[RESTART-MINER]${NC} Restarting miner only..."
    _stop_miner
    sleep 1
    _start_miner
}

cmd_tunnel_start() {
    echo -e "${CYAN}[TUNNEL-START]${NC} Starting Cloudflare tunnel..."
    _start_tunnel
}

cmd_tunnel_stop() {
    echo -e "${CYAN}[TUNNEL-STOP]${NC} Stopping Cloudflare tunnel..."
    _stop_tunnel
}

cmd_tunnel_restart() {
    echo -e "${CYAN}[TUNNEL-RESTART]${NC} Restarting Cloudflare tunnel..."
    _stop_tunnel
    sleep 1
    _start_tunnel
}

cmd_links() {
    local port
    port=$(_get_dashboard_port)
    local local_ip
    local_ip=$(hostname -I 2>/dev/null | awk '{print $1}')
    echo -e "\n${CYAN}── Dashboard Links ──────────────────────${NC}"
    echo -e "  Local   : ${BLUE}http://localhost:$port${NC}"
    [ -n "$local_ip" ] && echo -e "  Network : ${BLUE}http://$local_ip:$port${NC}"
    local tunnel_pid
    tunnel_pid=$(_read_pid "$TUNNEL_PID_FILE")
    if [ -f "$TUNNEL_URL_FILE" ] && _pid_running "$tunnel_pid"; then
        echo -e "  Tunnel  : ${BLUE}$(cat "$TUNNEL_URL_FILE")${NC}"
    elif [ -f "$TUNNEL_URL_FILE" ]; then
        echo -e "  Tunnel  : ${YELLOW}(tunnel stopped — last URL: $(cat "$TUNNEL_URL_FILE"))${NC}"
    else
        echo -e "  Tunnel  : ${YELLOW}not running — use: bash miner.sh tunnel-start${NC}"
    fi
    echo ""
}

cmd_status() {
    echo -e "\n${CYAN}── Status ───────────────────────────────${NC}"
    _status_miner
    _status_dashboard
    _status_tunnel
    echo ""
    cmd_links
}

cmd_logs() {
    if [[ ! -f "$LOG_FILE" ]]; then
        echo -e "${YELLOW}[WARN]${NC} No miner log yet at $LOG_FILE"
        return 1
    fi
    echo -e "${CYAN}[LOGS]${NC} Tailing $LOG_FILE — press Ctrl+C to exit"
    echo "────────────────────────────────────────"
    tail -n 50 -f "$LOG_FILE"
}

cmd_dlogs() {
    if [[ ! -f "$DASHBOARD_LOG_FILE" ]]; then
        echo -e "${YELLOW}[WARN]${NC} No dashboard log yet at $DASHBOARD_LOG_FILE"
        return 1
    fi
    echo -e "${CYAN}[DASH LOGS]${NC} Tailing $DASHBOARD_LOG_FILE — press Ctrl+C to exit"
    echo "────────────────────────────────────────"
    tail -n 50 -f "$DASHBOARD_LOG_FILE"
}

# ─── dispatch ────────────────────────────────────────────────────────────────

case "${1:-}" in
    start)           cmd_start          ;;
    stop)            cmd_stop           ;;
    restart)         cmd_restart        ;;
    status)          cmd_status         ;;
    logs)            cmd_logs           ;;
    dlogs)           cmd_dlogs          ;;
    links)           cmd_links          ;;
    start-miner)     cmd_start_miner    ;;
    stop-miner)      cmd_stop_miner     ;;
    restart-miner)   cmd_restart_miner  ;;
    tunnel-start)    cmd_tunnel_start   ;;
    tunnel-stop)     cmd_tunnel_stop    ;;
    tunnel-restart)  cmd_tunnel_restart ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|logs|dlogs|links|start-miner|stop-miner|restart-miner|tunnel-start|tunnel-stop|tunnel-restart}"
        echo ""
        echo "  start           — launch miner + dashboard + tunnel in background"
        echo "  stop            — stop miner + dashboard + tunnel"
        echo "  restart         — stop then start all three"
        echo "  status          — show running state, PIDs, and links"
        echo "  logs            — tail live miner output (Ctrl+C exits)"
        echo "  dlogs           — tail live dashboard output (Ctrl+C exits)"
        echo "  links           — show local and Cloudflare tunnel URLs"
        echo "  start-miner     — start miner only"
        echo "  stop-miner      — stop miner only"
        echo "  restart-miner   — restart miner only"
        echo "  tunnel-start    — start Cloudflare tunnel, print public URL"
        echo "  tunnel-stop     — stop Cloudflare tunnel"
        echo "  tunnel-restart  — restart Cloudflare tunnel (new URL)"
        exit 1
        ;;
esac
