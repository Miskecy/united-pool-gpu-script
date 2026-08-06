#!/bin/bash
# miner.sh — manage script.py as a background process
# Usage: ./miner.sh {start|stop|restart|status|logs}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="$SCRIPT_DIR/.venv/bin/python3"
PYTHON="$( [ -f "$VENV_PYTHON" ] && echo "$VENV_PYTHON" || echo "python3" )"
MAIN="$SCRIPT_DIR/script.py"
PID_FILE="$SCRIPT_DIR/.miner.pid"
LOG_FILE="$SCRIPT_DIR/miner.log"

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

# ─── commands ────────────────────────────────────────────────────────────────

cmd_start() {
    echo -e "${CYAN}[START]${NC} Launching miner..."
    _start_miner
}

cmd_stop() {
    echo -e "${CYAN}[STOP]${NC} Stopping miner..."
    _stop_miner
}

cmd_restart() {
    echo -e "${CYAN}[RESTART]${NC} Restarting miner..."
    _stop_miner
    sleep 1
    _start_miner
}

cmd_status() {
    echo -e "\n${CYAN}── Status ───────────────────────────────${NC}"
    _status_miner
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

# ─── dispatch ────────────────────────────────────────────────────────────────

case "${1:-}" in
    start)    cmd_start   ;;
    stop)     cmd_stop    ;;
    restart)  cmd_restart ;;
    status)   cmd_status  ;;
    logs)     cmd_logs    ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|logs}"
        echo ""
        echo "  start    — launch miner in background"
        echo "  stop     — stop miner"
        echo "  restart  — stop then start"
        echo "  status   — show running state and PID"
        echo "  logs     — tail live miner output (Ctrl+C exits)"
        exit 1
        ;;
esac
