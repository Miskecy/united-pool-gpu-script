# United GPU Script

<p align="center">
  <img  src="/index.jpg">
</p>

## Overview

This script is designed to fetch work blocks, execute cracking software (`vanitysearch2` or `BitCrack`), and manage the generated private keys. Key management includes sending notifications via Telegram and submitting found keys in batches to the API.

---

## Configuration

The script is configured using the `settings.json` file.

### Key Fields (Simplified)

| Field Name                    | Description                                                                     | Example Value                            |
| :---------------------------- | :------------------------------------------------------------------------------ | :--------------------------------------- |
| `api_url`                     | API base URL for fetching work blocks and posting results                       | `https://unitedpuzzlepool.com/api/block` |
| `user_token`                  | Pool token for worker authentication                                            | `a1b2c3d4e5f6`                           |
| `worker_name`                 | Human‑readable worker label used in Telegram                                    | `GPU-Rig-01`                             |
| `additional_addresses`        | Optional list of target addresses to stop on                                    | `["1AbCd..."]`                           |
| `gpu_index_map`               | **(New)** Per-GPU configuration for binary paths and workload shares            | _See below_                              |
| `program_arguments`           | Extra CLI arguments passed through verbatim                                     | `-g 1792,512`                            |
| `program_name`                | Behavior selector: `vanitysearch`, `bitcrack`, or `vanitysearch-v3` (lowercase) | `vanitysearch-v3`                        |
| `block_length`                | Requested block size (supports `K/M/B/T` suffixes)                              | `1T`                                     |
| `oneshot`                     | Run a single cycle and exit                                                     | `false`                                  |
| `post_block_delay_enabled`    | Enable delay between blocks                                                     | `true`                                   |
| `post_block_delay_minutes`    | Delay between iterations in minutes                                             | `2`                                      |
| `send_additional_keys_to_api` | Post keys found for `additional_addresses` to the API (default false)           | `false`                                  |

### ⚙️ Advanced GPU Configuration (`gpu_index_map`)

For mixed-GPU setups or to optimize performance across different cards, use `gpu_index_map`. This allows you to specify a different binary and workload share for each GPU index.

**Example:**

```json
"gpu_index_map": {
  "0": {
    "alg_path": "./bin/vanitysearch86-v3",
    "share": 65
  },
  "1": {
    "alg_path": "./bin/vanitysearch75-v3",
    "share": 35
  }
}
```

-   **`alg_path`**: The specific binary to run on this GPU (e.g., optimized for different CUDA Compute Capabilities).
-   **`share`**: An integer weight for splitting the keyspace. In the example above, GPU 0 gets 65% of the work, and GPU 1 gets 35%.

---

## Getting Your Pool Token (`user_token`)

You need a pool token to authenticate your worker when requesting blocks.

1. Web UI

    - Open `http://localhost:3000` and click `Generate Token`.
    - Copy the displayed token and set it in `settings.json` under `user_token`.

2. API (CLI)
    - Generate a token:
        ```bash
        curl -X POST http://localhost:3000/api/token/generate
        ```
    - You will receive a response containing your token. Set this value in `settings.json` → `user_token`.
    - Optional: verify a block request with your token:
        ```bash
        curl -H "pool-token: YOUR_TOKEN" "http://localhost:3000/api/block?length=1T"
        ```
    - The response includes `range.start`, `range.end`, and `checkwork_addresses` (count can be fewer than 10 for very small blocks).

---

## Behavior

### 🔄 Work Cycle

1. **New Block Notification:** When a new block is fetched, the script notifies with the range, total addresses, the GPU being used, and the selected algorithm.
2. **Key Cracking:** Executes the selected cracking software using the configured arguments.
3. **Processing `out.txt`:**
    - **Target Key Found:** If a key for an **`additional_address`** is found:
        - The `addr:priv` pair is saved to `KEYFOUND.txt`.
        - A special notification is sent to Telegram with the worker name.
        - Other normal keys are accumulated in `pending_keys.json`.
    - **Normal Key Found:** All non-target keys are accumulated in `pending_keys.json`.
4. **Key Submission:** Batches of **10–30 keys** are sent to the `api_url/submit` endpoint, matching the current block's `checkwork_addresses` count and API limits. The required batch size is derived from the current block’s addresses by counting lines in `in.txt`. If the queue has fewer keys than required, the script can auto‑generate valid filler keys uniformly within the current block range, but only when the previous run completed successfully.
    - **Incompatibility Handling:** If the API responds with an "incompatible privatekeys" error, the script immediately retries sending the same batch up to **3 times**. If all retries fail, it **clears `pending_keys`** and **fetches a new block** to avoid stalling.

### 🚀 One-Shot Mode (`oneshot: true`)

The script retries until it successfully fetches one block, then runs a single complete cycle (fetch, crack, process) and terminates.

### 🔁 Loop Mode (Default)

The script continuously loops until one of the following conditions is met:

-   A target key for an `additional_address` is found.
-   All available blocks have been solved (API returns a specific error).
-   The user manually interrupts the script.

### 🧠 Smart API Handling

-   If the requested `block_length` is too large for the remaining range, the API will adjust the size and assign a smaller block.
-   The API signals the completion of all work by returning status code `409` with the error message `{ "error": "All blocks are solved" }`.

---

## 📢 Telegram Status (Single Message)

Telegram messaging is provided by a dedicated module `telegram_status.py`. The script maintains a single message per worker and continuously edits it (no spam). It uses `parse_mode: HTML` with a worker header prepended.

### Format

-   `👷 Worker: <code>worker_name</code>`
-   `📊 Status` with the following lines:
    -   `🧩 Session: <code>session_id</code>`
    -   `⏳ Active: <code>duration</code>`
    -   `✅ Blocks: <code>count</code>`
    -   `🔁 Consecutive: <code>count</code>`
    -   `⚙️ GPU: <code>gpu_name</code>` (one GPU per line when multiple, no commas)
    -   `🧠 Algorithm: <code>executable_basename</code>`
    -   `🔧 Args: <code>executable_arguments</code>`
    -   `🧭 Range: <code>start:end</code>`
    -   `📫 Addresses: <code>count</code>`
    -   `📦 Pending Keys: <code>count</code>`
    -   `📤 Last Batch: <code>Sent N keys</code>` or error details
    -   `❗ Last Error: <i>message</i>`
    -   `🔑 Keyfound: <code>N saved to KEYFOUND.txt</code>`
    -   `⏱️ Next Fetch: <code>Xs</code>`
    -   `🧱 Total Length: <code>accumulated keyspace</code>` (K/M/G/T/P units)
    -   `🕒 Updated timestamp`
    -   `🏁 All blocks solved ✅` when applicable

### Example

```
👷 Worker: projetinho

📊 Status
🧩 Session: 3f7f7e12
⏳ Active: 50 mins
✅ Blocks: 1
🔁 Consecutive: 1
⚙️ GPU: GPU#0 NVIDIA GeForce RTX 4090
GPU#1 NVIDIA GeForce RTX 4090
GPU#2 NVIDIA GeForce RTX 4090
GPU#3 NVIDIA GeForce RTX 4090
🧠 Algorithm: VanitySearch-V3
🔧 Args: -gpu -gpuId 0 -g 1792,512
🧭 Range: 75760acbd8897d9fe9:75760ace93076ccfe9
📫 Addresses: 10
📦 Pending Keys: 0
📤 Last Batch: Sent 10 keys
❗ Last Error: -
🔑 Keyfound: -
⏱️ Next Fetch: 0s
🧱 Total Length: 1.23G
🕒 Updated 2025-12-12 04:32:18
```

### Notes

-   Implemented via `telegram_status.py` with state persistence in `telegram_state.json`.
-   Category‑based rate limiting avoids noisy updates (e.g., API errors vs. normal status lines).
-   HTML line breaks use real newlines (`\n`) and dynamic values are escaped to prevent parsing issues.
-   On HTML errors during creation, the module falls back to plain‑text creation and continues editing thereafter.
-   GPU entries in the `⚙️ GPU` line render one per line (no commas) for multi‑GPU setups.
-   `🧱 Total Length` accumulates the keyspace length per successfully processed block and shows a compact unit (K/M/G/T/P units).
-   `🕒 Updated` now shows a human‑friendly time‑ago based on the last status update.

### GPU and Algorithm Detection

-   **GPU Detection:** The script now uses `nvidia-smi` (if available) to detect GPU details, including Compute Capability. This allows for smarter defaults in mixed environments.
-   **Algorithm:** The Algorithm label is derived from the configured `alg_path` for each GPU.

---

## ▶️ Execution

1.  Ensure you have configured `settings.json` (especially `worker_name`).
2.  Run the script:
    ```bash
    python script.py
    ```
3.  Monitor log output and Telegram for real-time notifications.

### ⚡ Multi‑GPU Mode

-   When multiple GPUs are detected, the script automatically:
    -   Splits the fetched keyspace into N segments.
        -   **Weighted Splitting:** If `share` values are provided in `gpu_index_map`, the keyspace is split proportionally (e.g., a faster GPU gets a larger range).
        -   **Even Splitting:** Default behavior if no shares are defined.
    -   Launches N subprocesses, one per GPU.
    -   Writes per‑GPU outputs to `out_gpu_<i>.txt` and merges them back into `out.txt` for parsing.
-   VanitySearch/VanitySearch‑V2: the script adds `-gpuId <gid>` automatically per subprocess and filters any `-gpuId` you set in `program_arguments` to avoid conflicts.
-   Other tools: if your binary requires a device selector flag (e.g., BitCrack), include it in `program_arguments`. The script passes it through per subprocess.

### 🎯 Single‑GPU Mode

-   To run one GPU per instance (e.g., for manual orchestration), start multiple processes with `CUDA_VISIBLE_DEVICES=<id>` and omit device selectors in `program_arguments`. The script maps the visible device to index `0` for VanitySearch‑style binaries.

### ⚙️ Dynamic Configuration

The script reloads `settings.json` before starting each new work cycle. You can edit the configuration file _while the script is running_, and the changes will automatically take effect on the next iteration.

---

## Tool References

-   VanitySearch (official): https://github.com/JeanLucPons/VanitySearch
-   VanitySearch‑V3 (keyspace support): https://github.com/Miskecy/VanitySearch-V3
-   BitCrack (official): https://github.com/brichard19/BitCrack

Notes:
