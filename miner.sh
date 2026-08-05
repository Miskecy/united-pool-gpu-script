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

# ─── helpers ─────────────────────────────────────────────────────────────────

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'

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

# ─── commands ────────────────────────────────────────────────────────────────

cmd_start() {
    echo -e "${CYAN}[START]${NC} Launching miner + dashboard..."
    _start_miner
    _start_dashboard
}

cmd_stop() {
    echo -e "${CYAN}[STOP]${NC} Stopping miner + dashboard..."
    _stop_miner
    _stop_dashboard
}

cmd_restart() {
    echo -e "${CYAN}[RESTART]${NC} Restarting miner + dashboard..."
    _stop_miner
    _stop_dashboard
    sleep 1
    _start_miner
    _start_dashboard
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

cmd_status() {
    echo -e "\n${CYAN}── Status ───────────────────────────────${NC}"
    _status_miner
    _status_dashboard
    echo ""
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
    start)          cmd_start         ;;
    stop)           cmd_stop          ;;
    restart)        cmd_restart       ;;
    status)         cmd_status        ;;
    logs)           cmd_logs          ;;
    dlogs)          cmd_dlogs         ;;
    start-miner)    cmd_start_miner   ;;
    stop-miner)     cmd_stop_miner    ;;
    restart-miner)  cmd_restart_miner ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|logs|dlogs|start-miner|stop-miner|restart-miner}"
        echo ""
        echo "  start          — launch miner + dashboard in background"
        echo "  stop           — stop miner + dashboard"
        echo "  restart        — stop then start both"
        echo "  status         — show running state and PIDs for both"
        echo "  logs           — tail live miner output (Ctrl+C exits)"
        echo "  dlogs          — tail live dashboard output (Ctrl+C exits)"
        echo "  start-miner    — start miner only (dashboard keeps running)"
        echo "  stop-miner     — stop miner only (dashboard keeps running)"
        echo "  restart-miner  — restart miner only (dashboard keeps running)"
        exit 1
        ;;
esac
