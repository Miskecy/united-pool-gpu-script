# United GPU Script

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
| `program_path`                | Path to the cracking program binary                                             | `./VanitySearch-V2`                      |
| `program_arguments`           | Extra CLI arguments passed through verbatim                                     | `-g 1792,512`                            |
| `program_name`                | Behavior selector: `vanitysearch`, `bitcrack`, or `vanitysearch-v2` (lowercase) | `vanitysearch-v2`                        |
| `block_length`                | Requested block size (supports `K/M/B/T` suffixes)                              | `1T`                                     |
| `oneshot`                     | Run a single cycle and exit                                                     | `false`                                  |
| `post_block_delay_enabled`    | Enable delay between blocks                                                     | `true`                                   |
| `post_block_delay_minutes`    | Delay between iterations in minutes                                             | `2`                                      |
| `send_additional_keys_to_api` | Post keys found for `additional_addresses` to the API (default false)           | `false`                                  |

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
    -   `⚙️ GPU: <code>gpu_name</code>`
    -   `🧠 Algorithm: <code>executable_basename</code>`
    -   `🔧 Args: <code>executable_arguments</code>`
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
🔧 Args: -gpu -gpuId 0 -g 1792,512
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

-   GPU name is detected by invoking your configured program with the `-l` flag and selecting the `GPU #<gpuId>` lines.
-   The Algorithm label is derived directly from the executable file name (`program_path` basename, without extension). Name it as you prefer (e.g., `VanitySearch`, `VanitySearch-V2`, `BitCrack`).
-   For `api_url`, surrounding backticks and whitespace are trimmed automatically if present.

---

## ▶️ Execution

1.  Ensure you have configured `settings.json` (especially `worker_name`).
2.  Run the script:
    ```bash
    python script.py
    ```
3.  Monitor log output and Telegram for real-time notifications.

### ⚡ Multi‑GPU Mode

-   When multiple GPUs are detected via your binary’s `-l` listing, the script automatically:
    -   Splits the fetched keyspace evenly into N segments (where N = GPU count).
    -   Launches N subprocesses, one per GPU, printing per‑GPU start lines and live output.
    -   Writes per‑GPU outputs to `out_gpu_<i>.txt` and merges them back into `out.txt` for parsing.
    -   Cleans `out_gpu_<i>.txt` at start, after each run, after key posting, and after `out.txt` is cleared.
-   VanitySearch/VanitySearch‑V2: the script adds `-gpuId <gid>` automatically per subprocess and filters any `-gpuId` you set in `program_arguments` to avoid conflicts.
-   Other tools: if your binary requires a device selector flag (e.g., BitCrack), include it in `program_arguments`. The script passes it through per subprocess.

### 🎯 Single‑GPU Mode

-   To run one GPU per instance (e.g., for manual orchestration), start multiple processes with `CUDA_VISIBLE_DEVICES=<id>` and omit device selectors in `program_arguments`. The script maps the visible device to index `0` for VanitySearch‑style binaries.

### ⚙️ Dynamic Configuration

The script reloads `settings.json` before starting each new work cycle. You can edit the configuration file _while the script is running_, and the changes will automatically take effect on the next iteration.

---

## Tool References

-   VanitySearch (official): https://github.com/JeanLucPons/VanitySearch
-   VanitySearch‑V2 (keyspace support): https://github.com/ilkerccom/VanitySearch-V2
-   BitCrack (official): https://github.com/brichard19/BitCrack

Notes:

-   VanitySearch‑V2 supports `--keyspace` and multi‑address scanning. The script now supports multi‑GPU in a single instance by splitting the range and launching one subprocess per GPU.
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

### 🧹 Cleanup & Reliability

-   `out_gpu_<i>.txt` files are cleaned at start, before each run, after a successful run, after `out.txt` is cleared, and after a successful key post.
-   Batch size for submissions is derived from `in.txt` to match the block’s `checkwork_addresses` count.
-   Filler keys are generated only when the previous run completed successfully; they are disabled after failures.
-   When `send_additional_keys_to_api` is `true`, keys found for `additional_addresses` are also posted to the API in a dedicated call, in addition to being saved to `KEYFOUND.txt`.

---

## Bot Controller

The repository includes an optional Telegram‑based controller (`bot_controller.py`) that listens for commands and controls the worker script (`script.py`). It requires a Telegram bot token and chat ID and works alongside the existing status notifications.

### Setup

-   Configure `settings.json`:
    -   `telegram_accesstoken`: your Telegram bot token
    -   `telegram_chatid`: your chat ID
    -   `worker_name`: human‑readable server name (used for targeting)
-   Start the controller:
    ```bash
    python bot_controller.py
    ```

### Server Targeting

-   Each machine derives its server name from `worker_name` (or `SERVER_NAME` env, or system `COMPUTERNAME/HOSTNAME`).
-   Set a target with `/server <name>` to apply commands only to matching servers.
-   Clear the target with `/cleartarget` to broadcast commands again.
-   Commands also accept an inline target: `/stopscript <name>`.

### Server Discovery

-   Use `/serverlist` to discover available servers. The controller broadcasts presence and aggregates responses for a short window, then returns a formatted list.

### Safety Behavior

-   If `bot_controller.py` exits unexpectedly or is stopped, it attempts to terminate any worker process it started. This prevents orphaned workers.

### Commands

-   `/server <name>`: set target server name for subsequent commands.
-   `/cleartarget`: clear current target; broadcast commands to all.
-   `/startscript [name]`: start `script.py` on targeted servers.
-   `/stopscript [name]`: stop `script.py` on targeted servers.
-   `/restartscript [name]`: restart `script.py` on targeted servers.
-   `/status [name]`: show local status, server name, and current target.
-   `/whoami`: show local server name.
-   `/serverlist`: list discovered servers.
-   `/reloadsettings`: reload `settings.json` into the controller.
-   `/get <key>`: show the current value for `<key>`.
-   `/set <key> <value>`: update the value for `<key>`.

### `/get` and `/set` Details

-   Available keys are derived from `settings.json` and typically include:

    -   `api_url`: API base URL
    -   `user_token`: pool token
    -   `worker_name`: server name
    -   `program_name`: program identifier
    -   `program_path`: executable path
    -   `program_arguments`: CLI arguments
    -   `block_length`: keyspace block size
    -   `oneshot`: single‑block mode (bool)
    -   `post_block_delay_enabled`: delay toggle (bool)
    -   `post_block_delay_minutes`: delay minutes
    -   `additional_addresses`: list of extra addresses
    -   `telegram_share`: share toggle (bool)
    -   `telegram_accesstoken`: bot token
    -   `telegram_chatid`: chat ID

-   Value parsing:
    -   `true`/`false` → booleans
    -   numeric strings → integers/floats
    -   JSON objects/arrays → parsed structures
    -   other → raw string

### Help Output

-   The controller’s `/help` uses rich formatting (HTML) and includes targeting, worker control, settings management, and the dynamic list of available keys.
