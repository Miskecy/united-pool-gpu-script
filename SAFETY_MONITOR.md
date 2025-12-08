# Safety Monitor (`safety_monitor.sh`)

## Overview

-   Watchdog for NVIDIA GPUs that polls temperatures with `nvidia-smi`.
-   Monitors one or more GPU indices; when a GPU reaches the threshold, resets that GPU's clocks (`-rgc`).
-   Continues monitoring after resets to handle subsequent thermal spikes.

## Requirements

-   NVIDIA drivers installed and `nvidia-smi` available in PATH.
-   Privileges to change GPU clocks; `sudo` may be required on Linux.
-   Bash-compatible shell.

## Recommended Setup Sequence (Per-GPU)

-   Enable persistence mode to keep changes across operations:
    -   `sudo nvidia-smi -pm 1 -i 0`
-   Lock graphics (core) clock for a specific GPU (example GPU 1 at 1800 MHz):
    -   `sudo nvidia-smi -i 1 -lgc 1800,1800`
    -   `-i 1` targets GPU index 1
    -   `-lgc 1800,1800` locks the graphics clock between 1800 and 1800 MHz, preventing drift
-   Start the watchdog to protect that GPU:
    -   `bash safety_monitor.sh -t 82 -i 2 -g 1`

## Usage

-   Permission:
    -   `bash chmod +x safety_monitor.sh`
-   Help:
    -   `bash safety_monitor.sh -h`
-   Monitor specific GPUs:
    -   `bash safety_monitor.sh -t 82 -i 2 -g 0,1`
-   Monitor all GPUs:
    -   `bash safety_monitor.sh -g all`

## Options

-   `-t, --threshold <degC>`: Temperature threshold in °C (default: `82`).
-   `-i, --interval <seconds>`: Polling interval in seconds (default: `2`).
-   `-g, --gpus <list|all>`: Comma-separated GPU indices (e.g., `0,1`) or `all`.
-   `-h, --help`: Show usage.

## Behavior

-   Each poll reads temperature for selected GPUs via `nvidia-smi`.
-   When a GPU temperature `>= threshold`, the script runs `nvidia-smi -i <id> -rgc` for that GPU to reset clocks.
-   Monitoring continues indefinitely until interrupted (Ctrl+C) or the process is stopped.

## Reset or Unlock Clocks

-   Restore defaults for a specific GPU:
    -   `sudo nvidia-smi -i 1 -rgc`
-   The watchdog triggers this automatically for overheating GPUs.

## Examples

-   Lock GPU 1 to 1800 MHz and monitor only GPU 1 at 80°C every 1s:
    -   `sudo nvidia-smi -i 1 -lgc 1800,1800`
    -   `bash safety_monitor.sh -t 80 -i 1 -g 1`
-   Lock GPU 0 and GPU 1 to 1700 MHz, then monitor all:
    -   `sudo nvidia-smi -i 0 -lgc 1700,1700`
    -   `sudo nvidia-smi -i 1 -lgc 1700,1700`
    -   `bash safety_monitor.sh -g all`

## Notes

-   Omit `sudo` if not required by your environment (e.g., Windows).
-   Ensure cooling is adequate; locked high clocks increase thermal load.
-   If temperature read fails, the script logs a warning and continues.
-   `-g all` enumerates GPU indices using `nvidia-smi`.
