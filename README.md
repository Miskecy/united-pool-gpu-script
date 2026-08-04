# United GPU Script

<p align="center">
  <img src="/index.jpg">
</p>

A worker script for [United Puzzle Pool](https://unitedpuzzlepool.com). Fetches work blocks from the pool API, runs GPU cracking software (`VanitySearch-V3` or `BitCrack`) across all detected GPUs, and submits results automatically. Supports any number of GPUs with weighted keyspace splitting, real-time Telegram status updates, and a local web dashboard.

---

## Table of Contents

- [Requirements](#requirements)
- [Installation](#installation)
- [Getting Your Binaries](#getting-your-binaries)
- [Configuration](#configuration)
- [Telegram Setup](#telegram-setup)
- [Running the Miner](#running-the-miner)
- [Web Dashboard](#web-dashboard)
- [Managing in the Background (VPS / SSH)](#managing-in-the-background-vps--ssh)
- [How It Works](#how-it-works)
- [Troubleshooting](#troubleshooting)

---

## Requirements

- Ubuntu 22.04 (other Debian-based distros may work)
- NVIDIA GPU(s) with CUDA 12.8 compatible drivers
- Python 3.8+
- Internet access to reach the pool API

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/Miskecy/united-pool-gpu-script.git
cd united-pool-gpu-script
```

### 2. Run the automated setup script

```bash
bash miner_setup.sh
```

This installs everything needed and continues even if individual steps fail (e.g. NVIDIA download issues). It handles:

- System packages: `build-essential`, `git`, `python3`, `wget`, `curl`, `ca-certificates`
- NVIDIA CUDA 12.8 repository, compiler, libraries, and runtime
- CUDA environment variables written to `~/.bashrc`
- CUDA libs registered system-wide via `ldconfig` — no need to manually set `LD_LIBRARY_PATH`
- Python packages: `requests`, `colorama`, `flask`, `werkzeug`
- Execute permissions on binaries in `bin/`

At the end it prints a summary of any warnings or errors.

### 3. Reload your shell environment

```bash
source ~/.bashrc
```

### 4. Verify CUDA is available

```bash
nvcc --version
nvidia-smi
```

---

## Getting Your Binaries

The script does **not** include pre-built GPU binaries. You need to build or download them separately and place them in the `bin/` folder.

### VanitySearch-V3 (recommended)

Repository: https://github.com/Miskecy/VanitySearch-V3

Build for your GPU's Compute Capability:

| GPU Generation | Compute Capability | Build flag |
| :------------- | :----------------- | :--------- |
| RTX 40xx | sm_89 | `CCAP=89` |
| RTX 30xx | sm_86 | `CCAP=86` |
| RTX 20xx / GTX 16xx | sm_75 | `CCAP=75` |
| GTX 10xx | sm_61 | `CCAP=61` |

```bash
git clone https://github.com/Miskecy/VanitySearch-V3.git
cd VanitySearch-V3
make CCAP=86        # replace 86 with your GPU's compute capability
cp vanitysearch ../united-pool-gpu-script/bin/vanitysearch86-v3
```

If you have mixed GPUs, build once per compute capability and place both binaries in `bin/`.

### BitCrack (alternative)

Repository: https://github.com/brichard19/BitCrack

```bash
git clone https://github.com/brichard19/BitCrack.git
cd BitCrack
make BUILD_CUDA=1
cp bin/cuBitCrack ../united-pool-gpu-script/bin/
```

> You do **not** need to `chmod +x` binaries manually. The script auto-marks them executable before each launch.

---

## Configuration

Copy `settings_model.json` to `settings.json` and fill in your values:

```bash
cp settings_model.json settings.json
nano settings.json
```

`settings.json` is reloaded before every work cycle — changes take effect without restarting.

### Full settings reference

```json
{
    "api_url": "https://unitedpuzzlepool.com/api/block",
    "user_token": "YOUR_POOL_TOKEN",
    "worker_name": "GPU-Rig-01",
    "additional_addresses": ["1YourTargetBitcoinAddress..."],
    "program_name": "vanitysearch-v3",
    "gpu_index_map": { ... },
    "program_arguments": "",
    "block_length": "1T",
    "oneshot": false,
    "post_block_delay_enabled": false,
    "post_block_delay_minutes": 1,
    "send_additional_keys_to_api": false,
    "telegram_share": true,
    "telegram_accesstoken": "YOUR_BOT_TOKEN",
    "telegram_chatid": "YOUR_CHAT_ID",
    "dashboard_password": "",
    "dashboard_port": 8080
}
```

| Field | Description | Example |
| :---- | :---------- | :------ |
| `api_url` | Pool API base URL | `https://unitedpuzzlepool.com/api/block` |
| `user_token` | Your pool authentication token | `IOxQ4EbVt...` |
| `worker_name` | Label shown in Telegram and dashboard | `GPU-Rig-01` |
| `additional_addresses` | Bitcoin addresses to watch — script stops and saves the key if found | `["1PWo3J..."]` |
| `program_name` | Parser mode: `vanitysearch-v3`, `vanitysearch`, or `bitcrack` | `vanitysearch-v3` |
| `gpu_index_map` | Per-GPU binary and workload share — see below | |
| `program_arguments` | Extra CLI flags passed verbatim to the binary | `-g 1792,512` |
| `block_length` | Requested keyspace size (K/M/B/T suffixes supported) | `1T` |
| `oneshot` | Exit after one complete block instead of looping | `false` |
| `post_block_delay_enabled` | Wait between blocks | `false` |
| `post_block_delay_minutes` | How long to wait between blocks (minutes) | `1` |
| `send_additional_keys_to_api` | Also submit keys found for `additional_addresses` to the pool | `false` |
| `telegram_share` | Enable/disable Telegram notifications (can also be toggled from the dashboard) | `true` |
| `telegram_accesstoken` | Telegram bot token | `123456:ABC...` |
| `telegram_chatid` | Telegram chat/user ID to send status to | `468056589` |
| `dashboard_password` | Password for the web dashboard — leave empty to disable auth | `"mysecretpass"` |
| `dashboard_port` | Port the web dashboard listens on | `8080` |

### Getting your pool token

**Option A — Web UI:**

Open `https://unitedpuzzlepool.com`, log in, and generate a token from your dashboard.

**Option B — API:**

```bash
curl -X POST https://unitedpuzzlepool.com/api/token/generate
```

Verify it works:

```bash
curl -H "pool-token: YOUR_TOKEN" "https://unitedpuzzlepool.com/api/block?length=1T"
```

A successful response contains `range.start`, `range.end`, and `checkwork_addresses`.

### GPU configuration (`gpu_index_map`)

`gpu_index_map` tells the script which binary to use for each GPU and how to split the keyspace between them.

**`alg_path`** — path to the binary for this GPU index. Allows different GPUs to use different builds when their CUDA Compute Capabilities differ.

**`share`** — relative weight for keyspace splitting. The total range is divided proportionally. Use `1` for all GPUs to get equal splits.

> **Important:** List every GPU detected by `nvidia-smi`. An unlisted GPU defaults to `share: 1`, which becomes a tiny fraction if other entries have large values like `65`/`35`, causing it to finish instantly while others run for hours.

**Check your GPU indices:**

```bash
nvidia-smi --query-gpu=index,name --format=csv,noheader
```

**Example — identical GPUs, equal split:**

```json
"gpu_index_map": {
    "0":  { "alg_path": "./bin/vanitysearch86-v3", "share": 1 },
    "1":  { "alg_path": "./bin/vanitysearch86-v3", "share": 1 },
    "2":  { "alg_path": "./bin/vanitysearch86-v3", "share": 1 }
}
```

**Example — mixed GPU hardware, weighted split:**

```json
"gpu_index_map": {
    "0": { "alg_path": "./bin/vanitysearch86-v3", "share": 65 },
    "1": { "alg_path": "./bin/vanitysearch75-v3", "share": 35 }
}
```

---

## Telegram Setup

Telegram gives you a live status card per worker that is edited in place (no message spam).

### 1. Create a bot

1. Open Telegram and search for `@BotFather`
2. Send `/newbot` and follow the prompts
3. Copy the token (looks like `123456789:ABCdefGHI...`)
4. Paste it into `settings.json` → `telegram_accesstoken`

### 2. Get your chat ID

1. Search for `@userinfobot` on Telegram and send `/start`
2. It replies with your ID number
3. Paste it into `settings.json` → `telegram_chatid`

### 3. Start the bot

Send any message to your bot on Telegram. The first time the script runs it will create the status message automatically.

### Status card format

```
👷 Worker: GPU-Rig-01

📊 Status
🧩 Session: 3f7f7e12
⏳ Active: 50 mins
✅ Blocks: 12
🔁 Consecutive: 12
⚙️ GPU: GPU#0 NVIDIA GeForce RTX 4090
         GPU#1 NVIDIA GeForce RTX 4090
🧠 Algorithm: vanitysearch86-v3
🔧 Args: -
🧭 Range: 4ef4c37aba1a635c0d:4ef4c383d268d5fc0d
📫 Addresses: 11
📦 Pending Keys: 0
📤 Last Batch: Sent 11 keys
❗ Last Error: -
🔑 Keyfound: -
⏱️ Next Fetch: 0s
🧱 Total Length: 14.5T
🕒 Updated 2025-12-12 04:32:18
```

---

## Running the Miner

### Foreground (interactive / debug)

```bash
python3 script.py
```

Press `Ctrl+C` to stop. Output is shown directly in the terminal. The dashboard is not started in this mode.

### Background via `miner.sh` (recommended for VPS)

`./miner.sh start` launches **both** the miner and the web dashboard in the background:

```bash
./miner.sh start          # launch miner + dashboard
./miner.sh status         # check both are running and see PIDs
./miner.sh logs           # tail live miner output — Ctrl+C exits without stopping
./miner.sh dlogs          # tail live dashboard output — Ctrl+C exits without stopping
./miner.sh stop           # stop both miner and dashboard
./miner.sh restart        # stop + start both (use after editing settings.json)
./miner.sh start-miner    # start miner only (dashboard keeps running)
./miner.sh stop-miner     # stop miner only (dashboard keeps running)
./miner.sh restart-miner  # restart miner only (dashboard keeps running)
```

All miner output is saved to `miner.log`. Dashboard output is saved to `dashboard.log`.

---

## Web Dashboard

The web dashboard gives you a real-time visual view of the miner from any browser — useful when running on a VPS.

### Access

After `./miner.sh start`, open your browser and go to:

```
http://YOUR_VPS_IP:8080
```

The port can be changed with `dashboard_port` in `settings.json`.

### Features

| Feature | Details |
| :------ | :------ |
| **Status cards** | Current keyspace, addresses, pending keys, last batch, last error, key found, GPU info |
| **GPU display** | Multiple GPUs shown as individual styled rows with index badge |
| **Session bar** | Uptime, blocks done, consecutive successes, keyspace searched, average speed, worker name, algorithm |
| **Average speed** | Live-computed from log output; rolling average of last 20 readings per GPU — single and multi-GPU |
| **Live log viewer** | Auto-tails `miner.log` with structured color coding — Info (blue), Warning (yellow), Error (red), Success (green), Found (purple) |
| **Log filter** | Filter by level: All / Info / Warning / Error / Success / Found |
| **File viewer** | Shows non-empty contents of `in.txt`, `out.txt`, and `pending_keys.json` — hidden when empty |
| **Telegram toggle** | Enable or disable Telegram notifications from the dashboard — no restart needed |
| **Miner controls** | Start / Restart / Stop buttons control `script.py` only; dashboard stays running |
| **Graceful stop** | "Stop After Block" — sets a flag so the miner exits cleanly after the current block finishes (cancellable) |
| **Emergency stop** | "Stop All" button immediately kills both the miner and the dashboard |
| **Auto-refresh** | Status cards poll every 3 seconds — no manual refresh needed |

### Password protection

Set a password in `settings.json` to require HTTP Basic Auth when opening the dashboard:

```json
"dashboard_password": "yourpassword"
```

Leave it empty (`""`) to allow access without a password.

> **Tip:** For production VPS deployments, put the dashboard behind an nginx reverse proxy with HTTPS. The dashboard itself uses plain HTTP.

---

## Managing in the Background (VPS / SSH)

When connecting via SSH you need the miner to keep running after you disconnect. `miner.sh` handles this with `nohup` and PID files — no extra tools required.

### First time setup

```bash
# SSH into your VPS
ssh user@your-vps-ip

# Go to the project folder
cd ~/united-pool-gpu-script

# Make the manager script executable
chmod +x miner.sh

# Start miner + dashboard
./miner.sh start

# Watch the miner output for a few seconds to confirm it is working
./miner.sh logs
# Press Ctrl+C to stop watching — the miner keeps running

# Disconnect from SSH — both processes continue in background
exit
```

### Checking on it later

```bash
ssh user@your-vps-ip
cd ~/united-pool-gpu-script

./miner.sh status     # are both still running?
./miner.sh logs       # see recent miner output
```

### Applying settings changes

Edit `settings.json` then restart — no need to touch anything else:

```bash
nano settings.json
./miner.sh restart
```

### Full workflow reference

| Goal | Command |
| :--- | :------ |
| Start miner + dashboard | `./miner.sh start` |
| Stop miner + dashboard | `./miner.sh stop` |
| Restart after config change | `./miner.sh restart` |
| Start miner only (dashboard stays up) | `./miner.sh start-miner` |
| Stop miner only (dashboard stays up) | `./miner.sh stop-miner` |
| Restart miner only (dashboard stays up) | `./miner.sh restart-miner` |
| Check if running | `./miner.sh status` |
| Watch live miner output | `./miner.sh logs` |
| Watch live dashboard output | `./miner.sh dlogs` |
| Run miner in foreground (debug) | `python3 script.py` |
| Run dashboard only | `python3 dashboard.py` |

---

## How It Works

### Work cycle (per block)

1. **Fetch block** — requests a keyspace range and target addresses from the pool API
2. **Write `in.txt`** — saves target addresses for the binary to search against
3. **Run binary** — launches one subprocess per GPU; each searches its assigned keyspace segment in parallel
4. **Process output** — parses results; if a target address key is found it is saved to `KEYFOUND.txt` and the script exits
5. **Submit keys** — posts the found keys to the pool API; if fewer than required, generates valid filler keys within the block range to complete the batch

### Multi-GPU behaviour

- `nvidia-smi` detects all GPU indices automatically
- Keyspace is split proportionally by `share` weights from `gpu_index_map`
- Each GPU runs its own subprocess and writes to `out_gpu_<id>.txt`
- All outputs are merged into `out.txt` after all GPUs finish
- `-gpuId <id>` is injected per subprocess automatically for VanitySearch-style binaries
- If any GPU fails to start, all already-running siblings are cleanly killed before the error is reported

### Key submission

- Keys from each block are kept isolated — no cross-block contamination
- If the API rejects a batch as incompatible, it is retried up to 3 times then discarded
- If posting fails 3 consecutive times for any reason, the queue is cleared and the script moves on
- The script never loops indefinitely — stale keys are always discarded automatically

### Dashboard data flow

- `script.py` writes `status.json` after every status update
- `dashboard.py` reads `status.json` on each poll (every 3 seconds from the browser)
- Logs are streamed live via Server-Sent Events (SSE) by tailing `miner.log`
- Miner controls (Start / Stop / Restart) call `miner.sh start-miner / stop-miner / restart-miner` — the dashboard process stays running
- "Stop After Block" creates a `.stop_after_block` flag file; `script.py` checks for it at the start of each loop and exits cleanly if found
- "Stop All" kills the miner via its PID file then sends `SIGTERM` to the dashboard itself via a background thread
- Average speed is computed client-side from SSE log lines — no server changes needed

---

## Troubleshooting

### `libcudart.so.12: cannot open shared object file`

The CUDA runtime library is not on the dynamic linker path. Fix permanently:

```bash
echo "/usr/local/cuda-12.8/lib64" | sudo tee /etc/ld.so.conf.d/cuda-12-8.conf
sudo ldconfig
```

Then restart the miner.

### Dashboard is not accessible from browser

1. Check it is running: `./miner.sh status`
2. Check the port is open on your VPS firewall:
   ```bash
   sudo ufw allow 8080
   ```
3. Check the dashboard log for errors: `./miner.sh dlogs`

### Miner exits immediately after `./miner.sh start`

Check the log for the actual error:

```bash
./miner.sh logs
```

Common causes: missing `settings.json`, wrong `api_url`, binary not found in `bin/`.

### All GPUs finish instantly, one takes very long

Your `gpu_index_map` has unequal `share` values but not all GPU indices are listed. GPUs without an entry default to `share: 1`, which is a tiny fraction of the total when other GPUs have values like `65` or `35`.

Fix: list every GPU index from `nvidia-smi` with equal shares:

```bash
nvidia-smi --query-gpu=index,name --format=csv,noheader
```

Then add each index to `gpu_index_map` with `"share": 1`.

### API keeps returning incompatible private keys

The script now automatically discards keys after 3 failed attempts and fetches a fresh block. If it happens repeatedly, verify:

1. Your `program_name` in `settings.json` matches your actual binary (`vanitysearch-v3` for VanitySearch-V3, `bitcrack` for BitCrack)
2. The binary is producing output in the expected format — run it manually once to check:
   ```bash
   ./bin/vanitysearch86-v3 -i in.txt -o test_out.txt --keyspace START:END -gpuId 0
   cat test_out.txt
   ```

### `settings.json` changes not taking effect

The script reloads `settings.json` before each block, not mid-block. If the GPU binary is running, wait for the current block to finish or use `./miner.sh restart`.

---

## Tool References

- VanitySearch-V3 (keyspace support): https://github.com/Miskecy/VanitySearch-V3
- VanitySearch (official): https://github.com/JeanLucPons/VanitySearch
- BitCrack (official): https://github.com/brichard19/BitCrack
