#!/bin/bash
# miner.sh — manage script.py as a background process
# Usage: ./miner.sh {start|stop|restart|status|logs}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="python3"
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
    [[ -f "$PID_FILE" ]] && cat "$PID_FILE" 2>/dev/null || echo ""
}

# ─── commands ────────────────────────────────────────────────────────────────

cmd_status() {
    local pid
    pid=$(_read_pid)
    if _pid_running "$pid"; then
        echo -e "${GREEN}[RUNNING]${NC} script.py — PID $pid"
        echo -e "  Log : $LOG_FILE"
        echo -e "  Uptime: $(ps -o etime= -p "$pid" 2>/dev/null | tr -d ' ')"
    else
        echo -e "${RED}[STOPPED]${NC} script.py is not running."
        [[ -f "$PID_FILE" ]] && rm -f "$PID_FILE"
    fi
}

cmd_start() {
    local pid
    pid=$(_read_pid)
    if _pid_running "$pid"; then
        echo -e "${YELLOW}[WARN]${NC} Already running — PID $pid. Use 'restart' to reload."
        return 1
    fi

    echo -e "${CYAN}[START]${NC} Launching script.py in background..."
    nohup "$PYTHON" -u "$MAIN" >> "$LOG_FILE" 2>&1 &
    pid=$!
    echo "$pid" > "$PID_FILE"

    sleep 1
    if _pid_running "$pid"; then
        echo -e "${GREEN}[OK]${NC} Started — PID $pid"
        echo -e "  Log : tail -f $LOG_FILE"
    else
        echo -e "${RED}[FAIL]${NC} Process exited immediately. Check the log:"
        tail -20 "$LOG_FILE"
        rm -f "$PID_FILE"
        return 1
    fi
}

cmd_stop() {
    local pid
    pid=$(_read_pid)
    if ! _pid_running "$pid"; then
        echo -e "${YELLOW}[WARN]${NC} Not running."
        rm -f "$PID_FILE"
        return 0
    fi

    echo -e "${CYAN}[STOP]${NC} Stopping PID $pid..."
    kill "$pid" 2>/dev/null

    local waited=0
    while _pid_running "$pid" && (( waited < 10 )); do
        sleep 1
        (( waited++ ))
    done

    if _pid_running "$pid"; then
        echo -e "${YELLOW}[WARN]${NC} Process did not exit cleanly — sending SIGKILL..."
        kill -9 "$pid" 2>/dev/null
    fi

    rm -f "$PID_FILE"
    echo -e "${GREEN}[OK]${NC} Stopped."
}

cmd_restart() {
    echo -e "${CYAN}[RESTART]${NC} Restarting..."
    cmd_stop
    sleep 1
    cmd_start
}

cmd_logs() {
    if [[ ! -f "$LOG_FILE" ]]; then
        echo -e "${YELLOW}[WARN]${NC} No log file yet at $LOG_FILE"
        return 1
    fi
    echo -e "${CYAN}[LOGS]${NC} Tailing $LOG_FILE — press Ctrl+C to exit"
    echo "────────────────────────────────────────"
    tail -n 50 -f "$LOG_FILE"
}

# ─── dispatch ────────────────────────────────────────────────────────────────

case "${1:-}" in
    start)   cmd_start   ;;
    stop)    cmd_stop    ;;
    restart) cmd_restart ;;
    status)  cmd_status  ;;
    logs)    cmd_logs    ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|logs}"
        echo ""
        echo "  start    — launch script.py in the background"
        echo "  stop     — gracefully stop the running process"
        echo "  restart  — stop then start"
        echo "  status   — show whether it is running and its PID"
        echo "  logs     — tail the live log output (Ctrl+C to exit)"
        exit 1
        ;;
esac
