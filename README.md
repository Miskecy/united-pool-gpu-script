# United GPU Script

<p align="center">
  <img  src="/index.jpg">
</p>

## Overview

This script fetches work blocks from a pool API, executes GPU cracking software (`VanitySearch-V3` or `BitCrack`), and manages the generated private keys. Key management includes sending real-time status notifications via Telegram and submitting found keys in batches to the API.

Supports any number of GPUs with automatic detection via `nvidia-smi`, per-GPU binary selection, and weighted keyspace splitting.

---

## Setup

Run `miner_setup.sh` on a fresh Ubuntu 22.04 machine to install all dependencies automatically:

```bash
bash miner_setup.sh
```

The script is fully resilient — it continues even if individual steps fail (e.g. NVIDIA download issues) and prints a summary of warnings and errors at the end. It handles:

- System packages (`build-essential`, `git`, `python3`, `wget`, etc.)
- NVIDIA CUDA 12.1 repository and packages (skipped gracefully if unavailable)
- CUDA environment variables written to `~/.bashrc`
- CUDA libs registered with `ldconfig` so `libcudart.so.12` is found in any shell session — no need to manually set `LD_LIBRARY_PATH`
- Python dependencies: `requests`, `colorama`
- Repository clone (or `git pull` if already present)
- Execute permissions on binaries in `bin/`

After setup, place your GPU binaries in `bin/` and configure `settings.json`.

> **Note:** If you add binaries to `bin/` after running setup, you do **not** need to `chmod +x` them manually. `script.py` automatically ensures each binary is executable before launching it.

---

## Configuration

The script is configured using the `settings.json` file. It is reloaded before every work cycle, so changes take effect without restarting.

### Key Fields

| Field | Description | Example |
| :---- | :---------- | :------ |
| `api_url` | API base URL for fetching work blocks and posting results | `https://unitedpuzzlepool.com/api/block` |
| `user_token` | Pool token for worker authentication | `a1b2c3d4e5f6` |
| `worker_name` | Human-readable worker label shown in Telegram | `GPU-Rig-01` |
| `additional_addresses` | List of target addresses — script stops and saves key if found | `["1AbCd..."]` |
| `gpu_index_map` | Per-GPU binary path and workload share — see below | |
| `program_arguments` | Extra CLI arguments passed verbatim to the binary | `-g 1792,512` |
| `program_name` | Behavior selector: `vanitysearch`, `bitcrack`, or `vanitysearch-v3` | `vanitysearch-v3` |
| `block_length` | Requested block size (supports `K/M/B/T` suffixes) | `1T` |
| `oneshot` | Run a single cycle and exit | `false` |
| `post_block_delay_enabled` | Enable delay between blocks | `true` |
| `post_block_delay_minutes` | Delay between iterations in minutes | `2` |
| `send_additional_keys_to_api` | Also post keys found for `additional_addresses` to the API | `false` |

### GPU Configuration (`gpu_index_map`)

`gpu_index_map` controls which binary runs on each GPU and how the keyspace is divided between them.

**`alg_path`** — binary to use for that GPU. Useful when GPUs have different CUDA Compute Capabilities and need different builds (e.g. sm_86 for RTX 30xx/40xx, sm_75 for RTX 20xx).

**`share`** — integer weight for keyspace splitting. The script divides the total range proportionally by share values. Use equal values (e.g. all `1`) for equal distribution across identical GPUs.

> GPUs detected by `nvidia-smi` that have **no entry** in `gpu_index_map` default to `share: 1` and reuse the first configured binary automatically — they are never skipped.

**Example — 11 identical GPUs, equal split:**

```json
"gpu_index_map": {
    "0":  { "alg_path": "./bin/vanitysearch86-v3", "share": 1 },
    "1":  { "alg_path": "./bin/vanitysearch86-v3", "share": 1 },
    "2":  { "alg_path": "./bin/vanitysearch86-v3", "share": 1 },
    "3":  { "alg_path": "./bin/vanitysearch86-v3", "share": 1 },
    "4":  { "alg_path": "./bin/vanitysearch86-v3", "share": 1 },
    "5":  { "alg_path": "./bin/vanitysearch86-v3", "share": 1 },
    "6":  { "alg_path": "./bin/vanitysearch86-v3", "share": 1 },
    "7":  { "alg_path": "./bin/vanitysearch86-v3", "share": 1 },
    "8":  { "alg_path": "./bin/vanitysearch86-v3", "share": 1 },
    "9":  { "alg_path": "./bin/vanitysearch86-v3", "share": 1 },
    "10": { "alg_path": "./bin/vanitysearch86-v3", "share": 1 }
}
```

**Example — 2 GPUs with different hardware, proportional split:**

```json
"gpu_index_map": {
    "0": { "alg_path": "./bin/vanitysearch86-v3", "share": 65 },
    "1": { "alg_path": "./bin/vanitysearch75-v3", "share": 35 }
}
```

> Make sure every detected GPU has an entry when using custom `share` values. An unlisted GPU defaults to `share: 1`, which becomes a tiny fraction if other GPUs have large share values (e.g. 65 + 35), causing them to finish near-instantly while the others work the full range.

---

## Getting Your Pool Token (`user_token`)

1. **Web UI** — open `http://localhost:3000`, click **Generate Token**, copy the value into `settings.json`.

2. **API (CLI)**:
    ```bash
    curl -X POST http://localhost:3000/api/token/generate
    ```
    Optional — verify a block request with your token:
    ```bash
    curl -H "pool-token: YOUR_TOKEN" "http://localhost:3000/api/block?length=1T"
    ```
    The response includes `range.start`, `range.end`, and `checkwork_addresses`.

---

## Execution

1. Configure `settings.json` (especially `api_url`, `user_token`, `worker_name`, and `gpu_index_map`).
2. Place GPU binaries in `bin/`.
3. Run:
    ```bash
    python3 script.py
    ```
4. Monitor log output and Telegram for real-time status.

---

## Behavior

### Work Cycle

1. **Fetch block** — calls the pool API to get a keyspace range and target addresses.
2. **Write `in.txt`** — saves target addresses (including any `additional_addresses`).
3. **Run binary** — launches one subprocess per GPU, each searching its assigned segment.
4. **Process `out.txt`** — parses results after all GPU processes finish.
    - **Target key found:** saves `addr:priv` to `KEYFOUND.txt`, notifies Telegram, and exits.
    - **Normal keys found:** queued in `pending_keys.json` for batch posting.
5. **Submit keys** — posts batches of 10–30 keys to `api_url/submit`. If fewer keys than required are queued and the previous run succeeded, the script generates valid filler keys within the current block range to complete the batch.
    - If the API reports incompatible keys, the batch is retried up to **3 times** inside `post_private_keys`, then the queue is cleared and a new block is fetched.
    - If posting fails **3 consecutive times** for any reason (network error, server error, incompatible), the pending queue is cleared automatically and the script moves on — it will never loop indefinitely waiting to post.

### Multi-GPU Mode

When `nvidia-smi` detects multiple GPUs the script automatically:

- Splits the keyspace into N weighted segments (one per GPU).
- Launches N subprocesses simultaneously, one per GPU.
- Streams each GPU's output labeled `[GPU <id>]` in real time.
- Writes per-GPU output to `out_gpu_<id>.txt` and merges into `out.txt` after all finish.
- For VanitySearch-style binaries, injects `-gpuId <id>` per subprocess and strips any `-gpuId` from `program_arguments` to avoid conflicts.
- If a GPU fails to start, all already-running sibling processes are cleanly terminated before the error is reported.

### Single-GPU Mode

To manually assign one GPU per process, set `CUDA_VISIBLE_DEVICES` before running:

```bash
CUDA_VISIBLE_DEVICES=0 python3 script.py
```

The script maps the visible device to index `0` for VanitySearch-style binaries automatically.

### One-Shot Mode (`oneshot: true`)

Runs exactly one complete cycle (fetch → crack → submit) then exits.

### Loop Mode (default)

Runs continuously until:
- A key for an `additional_address` is found.
- The API signals all blocks are solved (`409 — All blocks are solved`).
- The user interrupts (`Ctrl+C`).

### Smart API Handling

- If `block_length` is too large for the remaining range, the API assigns a smaller block automatically.
- On server errors (5xx), the script waits and retries without resetting state.
- On repeated "no active block" errors (3 consecutive), pending keys are cleared and a fresh block is fetched.

---

## Telegram Status

A single Telegram message per worker is maintained and edited in place (no spam). Powered by `telegram_status.py` with state persisted in `telegram_state.json`.

### Format

```
👷 Worker: worker_name

📊 Status
🧩 Session: 3f7f7e12
⏳ Active: 50 mins
✅ Blocks: 1
🔁 Consecutive: 1
⚙️ GPU: GPU#0 NVIDIA GeForce RTX 4090
         GPU#1 NVIDIA GeForce RTX 4090
         ...
🧠 Algorithm: vanitysearch86-v3
🔧 Args: -gpu -g 1792,512
🧭 Range: 4ef4c37aba1a635c0d:4ef4c383d268d5fc0d
📫 Addresses: 11
📦 Pending Keys: 0
📤 Last Batch: Sent 11 keys
❗ Last Error: -
🔑 Keyfound: -
⏱️ Next Fetch: 0s
🧱 Total Length: 1.23G
🕒 Updated 2025-12-12 04:32:18
```

- GPU names are listed one per line (no commas) for multi-GPU setups.
- `🧱 Total Length` accumulates keyspace across all successfully processed blocks in the session.
- Rate limiting per error category prevents noisy repeated updates.
- Falls back to plain text if Telegram rejects HTML formatting.

---

## Tool References

- VanitySearch (official): https://github.com/JeanLucPons/VanitySearch
- VanitySearch-V3 (keyspace support): https://github.com/Miskecy/VanitySearch-V3
- BitCrack (official): https://github.com/brichard19/BitCrack
