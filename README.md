# United GPU Script

## Overview

This script is designed to fetch work blocks, execute cracking software (`vanitysearch2` or `BitCrack`), and manage the generated private keys. Key management includes sending notifications via Telegram and submitting found keys in batches to the API.

---

## Configuration

The script is configured using the `settings.json` file.

### Key Fields:

| Field Name                                    | Description                                                                                                         | Example Value            |
| :-------------------------------------------- | :------------------------------------------------------------------------------------------------------------------ | :----------------------- |
| `api_url`                                     | The URL of the API used to fetch work blocks.                                                                       | `https://api.pool.com/`  |
| `user_token`                                  | The pool token required for worker authentication.                                                                  | `a1b2c3d4e5f6`           |
| `worker_name`                                 | A unique name for the worker, used in notifications.                                                                | `GPU-Rig-01`             |
| `additional_address` / `additional_addresses` | The target address(es) to search for (high-value targets).                                                          | `1AbCd...`               |
| `vanitysearch_path`                           | The file path to the `VanitySearch` binary.                                                                         | `./VanitySearch`         |
| `vanitysearch_arguments`                      | Extra command-line arguments for `VanitySearch`.                                                                    | `--threads 4`            |
| `bitcrack_path`                               | The file path to the `BitCrack` binary (e.g., `cuBitCrack`).                                                        | `./cuBitCrack`           |
| `bitcrack_arguments`                          | Extra command-line arguments for `BitCrack`.                                                                        | `-t 256 -b 128 -p 64 -c` |
| `gpu_count` / `gpu_index`                     | Total number of GPUs and the index of the GPU to be utilized.                                                       | `4` / `0`                |
| `block_length`                                | The requested size of the work block (supports `K/M/B/T` suffixes).                                                 | `1T`                     |
| `auto_switch`                                 | If `true`, automatically selects the best app: `BitCrack` for blocks $< 1T$ with one GPU, `VanitySearch` otherwise. | `true`                   |
| `telegram_accesstoken`                        | The access token for your Telegram bot.                                                                             | `123456:ABC-DEF123456`   |
| `telegram_chatid`                             | The chat ID for receiving Telegram notifications.                                                                   | `-1001234567890`         |
| `oneshot`                                     | If `true`, the script performs one single cycle and then exits.                                                     | `false`                  |
| `post_block_delay_enabled`                    | Enable/disable delay between blocks. If `false`, no wait between blocks.                                            | `true`                   |
| `post_block_delay_minutes`                    | Delay between finishing a block and fetching the next, in minutes (used only if enabled). Default: `10s`.           | `1.5`                    |

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

1. **New Block Notification:** When a new block is fetched, the script notifies with the range, total addresses, and the GPU being used.
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

The script maintains a single Telegram message and continuously edits it for clean, organized updates (no spam). It uses `parse_mode: HTML` with a worker header prepended.

### Format

-   `👷 Worker: <code>worker_name</code>`
-   `📊 Status` with the following lines:
    -   `⚙️ GPU: <code>gpu_index</code>`
    -   `🧭 Range: <code>start:end</code>`
    -   `📫 Addresses: <code>count</code>`
    -   `📦 Pending Keys: <code>count</code>`
    -   `📤 Last Batch: <code>Sent N keys</code>` or error details
    -   `❗ Last Error: <i>message</i>`
    -   `🔑 Keyfound: <code>N saved to KEYFOUND.txt</code>`
    -   `⏱️ Next Fetch: <code>Xs</code>`
    -   `🕒 Updated timestamp`
    -   `🏁 All blocks solved ✅` when applicable

### Notes

-   HTML line breaks use real newlines (`\n`), not `<br>`.
-   The script escapes dynamic values to prevent HTML parsing issues.
-   A small state file `telegram_state.json` stores the Telegram `message_id` per worker; this allows the script to resume editing the same message after restarts.
-   On HTML errors during creation, the script falls back to plain-text creation automatically and continues editing thereafter.

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
-   Adjust `vanitysearch_arguments` or `bitcrack_arguments` in `settings.json` for performance tuning.

## 💾 Files

-   `in.txt`: Input addresses file used by the cracking application.
-   `out.txt`: Output file generated by `vanitysearch2`.
-   `KEYFOUND.txt`: Stores `addr:priv` pairs when an `additional_address` key is successfully found.
-   `pending_keys.json`: Queue of private keys awaiting batch submission to the API. Flushed in dynamic batches (10–30), with range‑safe filler keys automatically added when the queue is short; cleared after **3 failed retries** on API "incompatible privatekeys" responses.
-   `telegram_state.json`: Persists the Telegram `message_id` per worker to enable single-message editing across restarts.
