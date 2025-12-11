# United GPU Script

## Overview

This script is designed to fetch work blocks, execute cracking software (`vanitysearch2` or `BitCrack`), and manage the generated private keys. Key management includes sending notifications via Telegram and submitting found keys in batches to the API.

---

## Configuration

The script is configured using the `settings.json` file.

### Key Fields (Simplified)

| Field Name                 | Description                                                                     | Example Value                            |
| :------------------------- | :------------------------------------------------------------------------------ | :--------------------------------------- |
| `api_url`                  | API base URL for fetching work blocks and posting results                       | `https://unitedpuzzlepool.com/api/block` |
| `user_token`               | Pool token for worker authentication                                            | `a1b2c3d4e5f6`                           |
| `worker_name`              | Human‑readable worker label used in Telegram                                    | `GPU-Rig-01`                             |
| `additional_addresses`     | Optional list of target addresses to stop on                                    | `["1AbCd..."]`                           |
| `program_path`             | Path to the cracking program binary                                             | `./VanitySearch-V2`                      |
| `program_arguments`        | Extra CLI arguments passed through verbatim                                     | `-g 1792,512`                            |
| `program_name`             | Behavior selector: `vanitysearch`, `bitcrack`, or `vanitysearch-v2` (lowercase) | `vanitysearch-v2`                        |
| `block_length`             | Requested block size (supports `K/M/B/T` suffixes)                              | `1T`                                     |
| `oneshot`                  | Run a single cycle and exit                                                     | `false`                                  |
| `post_block_delay_enabled` | Enable delay between blocks                                                     | `true`                                   |
| `post_block_delay_minutes` | Delay between iterations in minutes                                             | `2`                                      |

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
4. **Key Submission:** Batches of **10–30 keys** are sent to the `api_url/submit` endpoint, matching the current block's `checkwork_addresses` count and API limits. If the queue has fewer keys than required, the script auto‑generates valid filler keys uniformly within the current block range to reach the required batch size. Success and failure are logged and notified.
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
    -   `⚙️ GPU: <code>gpu_name</code>`
    -   `🧠 Algorithm: <code>VanitySearch | VanitySearch-V2 | BitCrack</code>`
    -   `🧭 Range: <code>start:end</code>`
    -   `📫 Addresses: <code>count</code>`
    -   `📦 Pending Keys: <code>count</code>`
    -   `📤 Last Batch: <code>Sent N keys</code>` or error details
    -   `❗ Last Error: <i>message</i>`
    -   `🔑 Keyfound: <code>N saved to KEYFOUND.txt</code>`
    -   `⏱️ Next Fetch: <code>Xs</code>`
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
⚙️ GPU: NVIDIA GeForce RTX 3090 Ti
🧠 Algorithm: VanitySearch-V3
🧭 Range: 75760acbd8897d9fe9:75760ace93076ccfe9
📫 Addresses: 10
📦 Pending Keys: 0
📤 Last Batch: Sent 10 keys
❗ Last Error: -
🔑 Keyfound: -
⏱️ Next Fetch: 0s
🕒 Updated 2025-12-08 12:20:44
```

### Notes

-   Implemented via `telegram_status.py` with state persistence in `telegram_state.json`.
-   Category‑based rate limiting avoids noisy updates (e.g., API errors vs. normal status lines).
-   HTML line breaks use real newlines (`\n`) and dynamic values are escaped to prevent parsing issues.
-   On HTML errors during creation, the module falls back to plain‑text creation and continues editing thereafter.

### GPU and Algorithm Detection

-   GPU name is detected by invoking your configured program with the `-l` flag and selecting the `GPU #<gpuId>` line, where `<gpuId>` is taken from `program_arguments` (e.g., `-gpuId 0`). The detected name is cached per run.
-   The Algorithm label is derived from either the executable path (`program_path`) or `program_name` and displays one of `VanitySearch`, `VanitySearch-V2`, or `BitCrack`.
-   For `api_url`, surrounding backticks and whitespace are trimmed automatically if present.

---

## ▶️ Execution

1.  Ensure you have configured `settings.json` (especially `worker_name`).
2.  Run the script:
    ```bash
    python script.py
    ```
3.  Monitor log output and Telegram for real-time notifications.

### ⚙️ Dynamic Configuration

The script reloads `settings.json` before starting each new work cycle. You can edit the configuration file _while the script is running_, and the changes will automatically take effect on the next iteration.

---

## Tool References

-   VanitySearch (official): https://github.com/JeanLucPons/VanitySearch
-   VanitySearch‑V2 (keyspace support): https://github.com/ilkerccom/VanitySearch-V2
-   BitCrack (official): https://github.com/brichard19/BitCrack

Notes:

-   VanitySearch‑V2 supports `--keyspace` and multi‑address scanning. Use one GPU per instance; run separate instances for multi‑GPU.
-   Configure runtime via `program_path`, `program_arguments`, and `program_name`.

-   `in.txt`: Input addresses file used by the cracking application.
-   `out.txt`: Output file generated by the selected cracking program.
-   `KEYFOUND.txt`: Stores `addr:priv` pairs when an `additional_address` key is successfully found.
-   `pending_keys.json`: Queue of private keys awaiting batch submission to the API. Flushed in dynamic batches (10–30), with range‑safe filler keys automatically added when the queue is short; cleared after **3 failed retries** on API "incompatible privatekeys" responses.
-   `telegram_state.json`: Persists the Telegram `message_id` per worker to enable single‑message editing across restarts.
-   `telegram_status.py`: External module that manages Telegram status creation/editing and notifications.

### API Payload Format (privateKeys)

-   Posted keys are an array of 64‑character hex strings (uppercase), without `0x`.
-   Example: `{"privateKeys": ["0000...195B", "0000...846F", ...]}`

### Output Parsing

-   `output_parsers.py` routes based on `program_name` and supports VanitySearch‑V2 padded formats.
-   For VanitySearch‑V3, lines like `Priv (HEX): 0x <padded hex>` are normalized to 64 hex characters.
    -   `bash safety_monitor.sh -g all`
