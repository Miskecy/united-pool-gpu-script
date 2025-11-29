# -*- coding: utf-8 -*-
"""
Main worker script: fetch work blocks, run the external key cracker
(VanitySearch or BitCrack), parse results, and notify status/errors via Telegram.
"""
import requests
import os
import subprocess
import time
import sys
from datetime import datetime
from colorama import Fore, Style, init
import json
import shlex
import re

def _load_settings():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base_dir, "settings.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

_SETTINGS = _load_settings()

# --- File Configuration ---
IN_FILE = "in.txt"
OUT_FILE = "out.txt"
KEYFOUND_FILE = "KEYFOUND.txt"

TELEGRAM_BOT_TOKEN = ""
TELEGRAM_CHAT_ID = ""
API_URL = ""
POOL_TOKEN = ""
ADDITIONAL_ADDRESSES = []
BLOCK_LENGTH = ""
APP_PATH = ""
APP_ARGS = ""
GPU_INDEX = "0"
BITCRACK_PATH = ""
BITCRACK_ARGS = ""
AUTO_SWITCH = False
GPU_COUNT = 1
PROGRAM_BASE_COMMAND = []
WORKER_NAME = ""

ONE_SHOT = False
POST_BLOCK_DELAY_SECONDS = 10
POST_BLOCK_DELAY_ENABLED = True

def _apply_settings(s):
    global TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, API_URL, POOL_TOKEN, ADDITIONAL_ADDRESSES, BLOCK_LENGTH
    global APP_PATH, APP_ARGS, GPU_INDEX, PROGRAM_BASE_COMMAND, WORKER_NAME, ONE_SHOT
    global BITCRACK_PATH, BITCRACK_ARGS, AUTO_SWITCH, GPU_COUNT
    global POST_BLOCK_DELAY_SECONDS, POST_BLOCK_DELAY_ENABLED
    TELEGRAM_BOT_TOKEN = s.get("telegram_accesstoken", "")
    TELEGRAM_CHAT_ID = str(s.get("telegram_chatid", ""))
    API_URL = s.get("api_url", "")
    POOL_TOKEN = s.get("user_token", "")
    addrs = s.get("additional_addresses", [])
    if isinstance(addrs, list):
        ADDITIONAL_ADDRESSES = [a for a in addrs if isinstance(a, str) and a.strip()]
    else:
        ADDITIONAL_ADDRESSES = []
    legacy_addr = s.get("additional_address", "")
    if isinstance(legacy_addr, str) and legacy_addr.strip() and legacy_addr not in ADDITIONAL_ADDRESSES:
        ADDITIONAL_ADDRESSES.append(legacy_addr)
    BLOCK_LENGTH = s.get("block_length", "")
    APP_PATH = s.get("vanitysearch_path", s.get("app_path", ""))
    APP_ARGS = s.get("vanitysearch_arguments", s.get("app_arguments", ""))
    GPU_INDEX = str(s.get("gpu_index", 0))
    GPU_COUNT = int(s.get("gpu_count", 1) or 1)
    WORKER_NAME = s.get("worker_name", "") or s.get("workername", "")
    ONE_SHOT = bool(s.get("oneshot", False))
    BITCRACK_PATH = s.get("bitcrack_path", "")
    BITCRACK_ARGS = s.get("bitcrack_arguments", "")
    AUTO_SWITCH = bool(s.get("auto_switch", False))
    PROGRAM_BASE_COMMAND = [
        APP_PATH,
        "-t", "0",
        "-gpu",
        "-gpuId", GPU_INDEX,
        "-i", IN_FILE,
        "-o", OUT_FILE,
    ]
    if isinstance(APP_ARGS, str) and APP_ARGS.strip():
        PROGRAM_BASE_COMMAND += shlex.split(APP_ARGS)
    try:
        POST_BLOCK_DELAY_ENABLED = bool(s.get("post_block_delay_enabled", True))
    except Exception:
        POST_BLOCK_DELAY_ENABLED = True
    if POST_BLOCK_DELAY_ENABLED:
        delay_min = s.get("post_block_delay_minutes")
        try:
            if delay_min is not None:
                dm = float(delay_min)
                if dm < 0:
                    dm = 0
                POST_BLOCK_DELAY_SECONDS = int(dm * 60)
            else:
                POST_BLOCK_DELAY_SECONDS = 10
        except Exception:
            POST_BLOCK_DELAY_SECONDS = 10
    else:
        POST_BLOCK_DELAY_SECONDS = 0

def refresh_settings():
    s = _load_settings()
    _apply_settings(s)

_apply_settings(_SETTINGS)

# Initialize colorama
init(autoreset=True)

PENDING_KEYS = []
previous_keyspace = None
PENDING_KEYS_FILE = "pending_keys.json"
LAST_POST_ATTEMPT = 0
ALL_BLOCKS_SOLVED = False
PROCESSED_ONE_BLOCK = False

def _load_pending_keys():
    global PENDING_KEYS
    try:
        if os.path.exists(PENDING_KEYS_FILE):
            with open(PENDING_KEYS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    PENDING_KEYS = data
    except Exception:
        pass

def _save_pending_keys():
    try:
        with open(PENDING_KEYS_FILE, "w", encoding="utf-8") as f:
            json.dump(PENDING_KEYS, f)
    except Exception:
        pass

def _retry_pending_keys_now():
    global PENDING_KEYS
    posted = False
    while len(PENDING_KEYS) >= 10:
        batch = PENDING_KEYS[:10]
        if post_private_keys(batch):
            PENDING_KEYS = PENDING_KEYS[10:]
            posted = True
            _save_pending_keys()
        else:
            _save_pending_keys()
            break
    return posted

def _scheduled_pending_post_retry():
    global LAST_POST_ATTEMPT
    now = time.time()
    if now - LAST_POST_ATTEMPT >= 30 and len(PENDING_KEYS) >= 10:
        LAST_POST_ATTEMPT = now
        ok = _retry_pending_keys_now()
        if ok:
            logger("Success", "Pending keys posted successfully.")
        else:
            logger("Warning", "API unavailable. Keeping keys and retrying in 30s.")

def flush_pending_keys_blocking():
    global PENDING_KEYS
    posted = False
    while len(PENDING_KEYS) >= 10:
        batch = PENDING_KEYS[:10]
        if post_private_keys(batch):
            PENDING_KEYS = PENDING_KEYS[10:]
            posted = True
            _save_pending_keys()
        else:
            _save_pending_keys()
            time.sleep(30)
    return posted

def handle_next_block_immediately():
    refresh_settings()
    data = fetch_block_data()
    if not data:
        return False
    addresses = data.get("checkwork_addresses", [])
    range_data = data.get("range", {})
    start_hex = range_data.get("start", "").replace("0x", "")
    end_hex = range_data.get("end", "").replace("0x", "")
    keyspace = f"{start_hex}:{end_hex}"
    global previous_keyspace
    previous_keyspace = keyspace
    save_addresses_to_in_file(addresses, ADDITIONAL_ADDRESSES)
    run_external_program(start_hex, end_hex)
    return True
# ==============================================================================================
#                                    UTILITY & COMMUNICATION FUNCTIONS
# ==============================================================================================

def logger(level, message):
    """
    Print a message with timestamp and colored log level.
    """
    current_time = datetime.now()
    formatted_time = current_time.strftime("[%Y-%m-%d.%H:%M:%S]")
    
    color_map = {
        "Info": Fore.LIGHTBLUE_EX,
        "Warning": Fore.LIGHTYELLOW_EX,
        "Error": Fore.LIGHTRED_EX,
        "Success": Fore.LIGHTGREEN_EX,
        "KEYFOUND": Fore.LIGHTMAGENTA_EX,
        "Timer": Fore.LIGHTYELLOW_EX
    }
    
    color = color_map.get(level, Fore.WHITE)
    print(f"{formatted_time} {color}[{level}]{Style.RESET_ALL} {message}")

# ----------------------------------------------------------------------------------------------

def send_telegram_notification(message):
    """
    Send a notification message to Telegram.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger("Warning", "Telegram settings missing. Notification not sent.")
        return

    telegram_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    if WORKER_NAME:
        message = f"👷 Worker: `{WORKER_NAME}`\n\n{message}"
    payload = {
        "chat_id": str(TELEGRAM_CHAT_ID), 
        "text": message,
        "parse_mode": "Markdown"
    }

    try:
        response = requests.post(telegram_url, data=payload, timeout=10)
        if response.status_code == 200:
            logger("Success", "Telegram notification sent!")
        else:
            logger("Error", f"Error sending Telegram: Status {response.status_code}. Response: {response.text}")
    except requests.RequestException:
        logger("Error", "Request error while trying to send Telegram notification.")

# ----------------------------------------------------------------------------------------------

LAST_TELEGRAM_TS = {}

def send_telegram_notification_rl(message, category, min_interval):
    now = time.time()
    last = LAST_TELEGRAM_TS.get(category, 0)
    if now - last < min_interval:
        return
    LAST_TELEGRAM_TS[category] = now
    send_telegram_notification(message)

def fetch_block_data():
    """
    Fetch the work block from API and notify via Telegram on failure.
    """
    headers = {"pool-token": POOL_TOKEN, "ngrok-skip-browser-warning": "true", "User-Agent": "unitead-gpu-script/1.0"}
    
    try:
        logger("Info", f"Fetching data from {API_URL}")
        params = {"length": BLOCK_LENGTH} if BLOCK_LENGTH else None
        response = requests.get(API_URL, headers=headers, params=params, timeout=15)
        
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 409:
            try:
                data = response.json()
            except Exception:
                data = {"error": (response.text or "").strip()}
            msg = str(data.get("error", "")).strip()
            if msg.lower() == "all blocks are solved":
                global ALL_BLOCKS_SOLVED
                ALL_BLOCKS_SOLVED = True
                send_telegram_notification("🏁 **ALL BLOCKS ARE SOLVED**\n\nShutting down worker.")
                logger("Success", "All blocks solved. Shutting down.")
                return None
            error_message = (
                f"⚠️ **NO RANGE AVAILABLE**\n\n"
                f"Status: `409`\n"
                f"Detail: `{msg or 'No available random range'}`"
            )
            send_telegram_notification_rl(error_message, "no_range", 300)
            logger("Error", f"Error fetching block: 409 - {response.text}")
            return None
        else:
            error_message = (
                f"🚨 **ALERT: API DOWN OR ERROR!**\n\n"
                f"Failed to fetch work block.\n"
                f"Status: `{response.status_code}`. Response: {response.text[:100]}..."
            )
            send_telegram_notification_rl(error_message, "api_fetch_error", 300)
            logger("Error", f"Error fetching block: {response.status_code} - {response.text}")
            return None
            
    except requests.RequestException as e:
        error_message = (
            f"🚨 **ALERT: API CONNECTION ERROR!**\n\n"
            f"The script could not connect to the API.\n"
            f"Error Detail: `{type(e).__name__}` - {e}"
        )
        send_telegram_notification_rl(error_message, "api_fetch_error", 300)
        logger("Error", f"Request error {type(e).__name__}: {e}")
        return None

# ----------------------------------------------------------------------------------------------

def post_private_keys(private_keys):
    headers = {
        "pool-token": POOL_TOKEN,
        "Content-Type": "application/json",
        "ngrok-skip-browser-warning": "true",
        "User-Agent": "unitead-gpu-script/1.0"
    }
    if len(private_keys) != 10:
        logger("Warning", f"Batch ignored: exactly 10 keys required, got {len(private_keys)}")
        return False
    data = {"privateKeys": private_keys}
    logger("Info", "Posting batch of 10 private keys to API.")
    
    try:
        response = requests.post(API_URL+"/submit", headers=headers, json=data, timeout=10)
        if response.status_code == 200:
            logger("Success", "Private keys posted successfully.")
            success_message = (
                f"✅ **BATCH SENT**\n\n"
                f"Keys: `{len(private_keys)}`\n"
                f"Status: ✅ API OK"
            )
            send_telegram_notification(success_message)
            return True
        else:
            snippet = ""
            try:
                snippet = (response.text or "")[:120].replace("\n", " ")
            except Exception:
                snippet = ""
            logger("Error", f"Failed to send batch: Status {response.status_code}. Retrying in 30s.")
            if snippet:
                logger("Info", f"Detail: {snippet}...")
            error_message = (
                f"⚠️ **FAILED TO SEND BATCH**\n\n"
                f"Status: `{response.status_code}`\n"
                f"Will retry in `30s`. Data remains saved."
            )
            send_telegram_notification_rl(error_message, "post_error", 300)
            return False
    except requests.RequestException as e:
        logger("Error", f"Connection error while sending batch: {type(e).__name__}. Retrying in 30s.")
        error_message = (
            f"🌐 **CONNECTION ERROR ON SEND**\n\n"
            f"Detail: `{type(e).__name__}` - {e}\n"
            f"Will retry in `30s`. Data remains saved."
        )
        send_telegram_notification_rl(error_message, "post_network_error", 300)
        return False

# ==============================================================================================
#                                    MAIN WORK FUNCTIONS
# ==============================================================================================
# ... (Funções save_addresses_to_in_file, run_external_program e process_out_file não alteradas)
# ...

# ----------------------------------------------------------------------------------------------

def save_addresses_to_in_file(addresses, additional_addresses):
    all_addresses = list(addresses)
    extras = [a for a in (additional_addresses or []) if isinstance(a, str) and a.strip()]
    for a in extras:
        if a not in all_addresses:
            all_addresses.append(a)

    try:
        with open(IN_FILE, "w") as file:
            file.write("\n".join(all_addresses) + "\n")
        logger("Info", f"Addresses saved to '{IN_FILE}'. Total: {len(all_addresses)}")
    except Exception as e:
        logger("Error", f"Failed to save addresses to '{IN_FILE}': {e}")
        sys.exit(1)

def clean_io_files():
    try:
        with open(IN_FILE, "w"):
            pass
        with open(OUT_FILE, "w"):
            pass
    except Exception:
        pass

def clean_out_file():
    try:
        with open(OUT_FILE, "w"):
            pass
    except Exception:
        pass

# ----------------------------------------------------------------------------------------------

def _parse_length_to_count(s):
    try:
        if not s:
            return None
        txt = str(s).strip().upper()
        m = re.fullmatch(r"(\d+)([KMBT]?)", txt)
        if not m:
            return None
        val = int(m.group(1))
        unit = m.group(2)
        mult = {
            "K": 10**3,
            "M": 10**6,
            "B": 10**9,
            "T": 10**12,
        }.get(unit, 1)
        return int(val * mult)
    except Exception:
        return None

def run_external_program(start_hex, end_hex):
    """Run external program with given keyspace and stream live feedback."""
    keyspace = f"{start_hex}:{end_hex}"
    
    requested_len = _parse_length_to_count(BLOCK_LENGTH)
    try:
        actual_len = int(end_hex, 16) - int(start_hex, 16)
    except Exception:
        actual_len = None
    compare_len = requested_len if requested_len is not None else actual_len

    chosen = "vanity"
    if AUTO_SWITCH:
        if GPU_COUNT > 1:
            chosen = "vanity"
        else:
            if compare_len is not None and compare_len < 10**12 and BITCRACK_PATH:
                chosen = "bitcrack"
            else:
                chosen = "vanity"
    if chosen == "bitcrack" and not BITCRACK_PATH:
        chosen = "vanity"

    if chosen == "vanity":
        base = [
            APP_PATH,
            "-t", "0",
            "-gpu",
            "-i", IN_FILE,
            "-o", OUT_FILE,
        ]
        if GPU_COUNT <= 1:
            base += ["-gpuId", GPU_INDEX]
        if isinstance(APP_ARGS, str) and APP_ARGS.strip():
            base += shlex.split(APP_ARGS)
        command = base + ["--keyspace", keyspace]
    else:
        base = [
            BITCRACK_PATH,
            "-i", IN_FILE,
            "-o", OUT_FILE,
            "-d", GPU_INDEX,
        ]
        if isinstance(BITCRACK_ARGS, str) and BITCRACK_ARGS.strip():
            base += shlex.split(BITCRACK_ARGS)
        command = base + ["--keyspace", keyspace]
    clean_out_file()
    
    logger("Info", f"Running with keyspace: {Fore.GREEN}{keyspace}{Style.RESET_ALL}")

    try:
        # Use Popen to run the process and access real-time I/O streams
        with subprocess.Popen(
            command, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.STDOUT, 
            text=True, 
            bufsize=1 
        ) as process:
            
            # Read and display subprocess output line by line
            for line in process.stdout:
                # Real-time feedback
                print(f"{Fore.CYAN}  > {line.strip()}{Style.RESET_ALL}", flush=True)

            # Espera o processo terminar e verifica o código de retorno
            return_code = process.wait()

            if return_code == 0:
                logger("Success", "External program finished successfully")
                return True
            else:
                logger("Error", f"External program failed with return code: {return_code}")
                return False

    except FileNotFoundError:
        logger("Error", "External program not found. Check path and permissions.")
        return False
    except Exception as e:
        logger("Error", f"Exception while executing: {e}")
        return False

# ----------------------------------------------------------------------------------------------

def process_out_file():
    """
    Process out.txt, check additional address hit, notify via Telegram,
    and enqueue other keys for API posting.
    """
    global PENDING_KEYS
    if not os.path.exists(OUT_FILE):
        logger("Warning", f"File '{OUT_FILE}' not found for processing.")
        return False

    keys_to_post = []
    found_pairs = []
    
    try:
        # Read out.txt and extract keys
        with open(OUT_FILE, "r") as file:
            current_address = None
            extras_set = set([a for a in (ADDITIONAL_ADDRESSES or []) if isinstance(a, str)])
            for line in file:
                if "Pub Addr: " in line:
                    current_address = line.split("Pub Addr: ")[1].strip()
                elif "Priv (HEX): " in line and current_address:
                    private_key = line.split("Priv (HEX): ")[1].strip()
                    if current_address in extras_set:
                        found_pairs.append((current_address, private_key))
                    else:
                        keys_to_post.append(private_key)
                    current_address = None
                else:
                    raw = line.strip()
                    if raw:
                        parts = raw.split()
                        if len(parts) >= 2:
                            addr = parts[0].strip()
                            priv = parts[1].strip()
                            if re.fullmatch(r"(?:0x)?[0-9a-fA-F]{64}", priv):
                                if addr in extras_set:
                                    found_pairs.append((addr, priv))
                                else:
                                    keys_to_post.append(priv)
                        elif re.fullmatch(r"(?:0x)?[0-9a-fA-F]{64}", raw):
                            keys_to_post.append(raw)

    except Exception as e:
        logger("Error", f"Error processing file '{OUT_FILE}': {e}")
        return False

    # 1. Check and Save Additional Address hit (and Notify)
    if found_pairs:
        logger("KEYFOUND", f"{len(found_pairs)} key(s) for additional addresses found. Stopping...")
        
        # Save found private key to file
        try:
            with open(KEYFOUND_FILE, "w") as file:
                file.write("\n".join([f"{addr}:{key}" for (addr, key) in found_pairs]) + "\n")
            logger("KEYFOUND", f"Private key saved in '{KEYFOUND_FILE}'.")
        except Exception as e:
            logger("KEYFOUND Error", f"Failed to save private key to file: {e}")
        if keys_to_post:
            PENDING_KEYS.extend(keys_to_post)
            _save_pending_keys()
        addrs_list = "\n".join([f"`{addr}`" for (addr, _) in found_pairs])
        message = (
            f"🔑 **PRIVATE KEY FOUND**\n\n"
            f"Additional addresses:\n{addrs_list}\n\n"
            f"Regular keys accumulated: `{len(keys_to_post)}`\n"
            f"File: `{KEYFOUND_FILE}`"
        )
        send_telegram_notification(message)
        return True
    
    if keys_to_post:
        PENDING_KEYS.extend(keys_to_post)
        logger("Info", f"Accumulated {len(PENDING_KEYS)} keys for posting.")
        _save_pending_keys()

    # 3. Clear out.txt for the next cycle
    try:
        with open(OUT_FILE, "w"):
            pass
        logger("Info", f"File '{OUT_FILE}' cleared for next cycle.")
    except Exception as e:
        logger("Error", f"Failed to clear file '{OUT_FILE}': {e}")

    return False # Indicates the additional address key was NOT found

# ==============================================================================================
#                                    MAIN LOOP
# ==============================================================================================

if __name__ == "__main__":
    clean_io_files()
    refresh_settings()
    _load_pending_keys()
    while True:
        refresh_settings()
        flush_pending_keys_blocking()
        if ONE_SHOT and PROCESSED_ONE_BLOCK:
            logger("Info", "One-shot mode enabled. Exiting after first block.")
            break
        # 1. Fetch block data
        block_data = fetch_block_data()
        
        if ALL_BLOCKS_SOLVED:
            break
        if not block_data:
            logger("Error", "Could not fetch block data. Retrying in 30 seconds.")
            time.sleep(30)
            continue

        addresses = block_data.get("checkwork_addresses", [])
        range_data = block_data.get("range", {})
        start_hex = range_data.get("start", "").replace("0x", "")
        end_hex = range_data.get("end", "").replace("0x", "")
        current_keyspace = f"{start_hex}:{end_hex}" # (NEW)

        if not addresses:
            logger("Warning", "No addresses found in block. Retrying in 30 seconds.")
            time.sleep(30)
            continue

        if not (start_hex and end_hex):
            logger("Error", "Key range (start/end) missing. Retrying in 30 seconds.")
            time.sleep(30)
            continue
        
        # 2. New: New block notification logic
        if current_keyspace != previous_keyspace:
            previous_keyspace = current_keyspace
            
            new_block_message = (
                f"⛏️ **NEW BLOCK**\n\n"
                f"Range: `{current_keyspace}`\n"
                f"Addresses: `{len(addresses)}`\n"
                f"GPU: `{GPU_INDEX}`"
            )
            send_telegram_notification(new_block_message)
            logger("Info", f"New block notification sent: {current_keyspace}")

        # 3. Save addresses to in.txt
        save_addresses_to_in_file(addresses, ADDITIONAL_ADDRESSES)
        
        # 4. Run external program (no chunking)
        run_external_program(start_hex, end_hex)

        # 5. Process output file (out.txt)
        solution_found = process_out_file()

        PROCESSED_ONE_BLOCK = True
        # 6. Stop logic
        if solution_found:
            logger("Success", "ADDITIONAL ADDRESS KEY FOUND. Exiting script.")
            break

        flush_pending_keys_blocking()
        if ONE_SHOT:
            logger("Info", "One-shot mode enabled. Exiting after first block.")
            break
        logger("Info", f"No critical solution this round. Waiting {POST_BLOCK_DELAY_SECONDS} seconds for next fetch.")
        time.sleep(POST_BLOCK_DELAY_SECONDS)
