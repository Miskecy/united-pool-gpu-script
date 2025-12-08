#!/bin/bash
THRESHOLD=82
INTERVAL=2
GPU_ARG=""
GPU_IDS=()

usage() {
  echo "Usage: $0 [-t threshold] [-i interval] [-g gpu_ids|all]"
  echo "Example: $0 -t 82 -i 2 -g 0,1"
}

while [ $# -gt 0 ]; do
  case "$1" in
    -t|--threshold)
      THRESHOLD="$2"; shift 2;;
    -i|--interval)
      INTERVAL="$2"; shift 2;;
    -g|--gpus)
      GPU_ARG="$2"; shift 2;;
    -h|--help)
      usage; exit 0;;
    --)
      shift; break;;
    *)
      echo "Unknown option: $1"; usage; exit 1;;
  esac
done

if [ -z "$GPU_ARG" ]; then
  GPU_IDS=(0)
elif [ "$GPU_ARG" = "all" ]; then
  mapfile -t GPU_IDS < <(nvidia-smi --query-gpu=index --format=csv,noheader,nounits)
else
  IFS=',' read -r -a GPU_IDS <<< "$GPU_ARG"
fi

if ! [[ "$THRESHOLD" =~ ^[0-9]+$ ]]; then echo "Invalid threshold: $THRESHOLD"; exit 1; fi
if ! [[ "$INTERVAL" =~ ^[0-9]+$ ]]; then echo "Invalid interval: $INTERVAL"; exit 1; fi
for id in "${GPU_IDS[@]}"; do if ! [[ "$id" =~ ^[0-9]+$ ]]; then echo "Invalid GPU id: $id"; exit 1; fi; done

reset_clocks() {
  local id="$1"
  if command -v sudo >/dev/null 2>&1; then
    sudo nvidia-smi -i "$id" -rgc
  else
    nvidia-smi -i "$id" -rgc
  fi
}

echo "Monitoring GPUs: ${GPU_IDS[*]} | threshold ${THRESHOLD}°C | interval ${INTERVAL}s"

trap 'echo "Exiting"; exit 0' INT TERM

while true; do
  for id in "${GPU_IDS[@]}"; do
    TEMP=$(nvidia-smi -i "$id" --query-gpu=temperature.gpu --format=csv,noheader,nounits 2>/dev/null | tr -d '[:space:]')
    if [[ "$TEMP" =~ ^[0-9]+$ ]]; then
      if [ "$TEMP" -ge "$THRESHOLD" ]; then
        echo "CRITICAL: GPU $id temp ${TEMP}°C, resetting clocks"
        reset_clocks "$id"
      fi
    else
      echo "WARN: GPU $id temperature read failed"
    fi
  done
  sleep "$INTERVAL"
done
