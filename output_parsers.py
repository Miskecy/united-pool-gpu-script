import re

def _is_hex64(s):
    try:
        t = s.strip().lower().replace("0x", "")
        return len(t) == 64 and all(c in "0123456789abcdef" for c in t)
    except Exception:
        return False

def _norm_hex(s):
    t = s.strip().replace(" ", "")
    t = t.replace("0x", "")
    t = t.lower()
    if len(t) == 64 and _is_hex64(t):
        return t.upper()
    return None

def parse_vanity(text, extras):
    extras_set = set([a for a in (extras or []) if isinstance(a, str)])
    keys_to_post = []
    found_pairs = []
    current_address = None
    for line in text.splitlines():
        if "Pub Addr:" in line or "PubAddress:" in line or "Public Addr:" in line or "Public Address:" in line:
            try:
                if "Pub Addr:" in line:
                    token = "Pub Addr:"
                elif "PubAddress:" in line:
                    token = "PubAddress:"
                elif "Public Addr:" in line:
                    token = "Public Addr:"
                else:
                    token = "Public Address:"
                current_address = line.split(token, 1)[1].strip()
            except Exception:
                current_address = None
            continue
        if "Priv (HEX):" in line:
            raw = line.split("Priv (HEX):", 1)[1]
            hx = _norm_hex(raw or "")
            if hx and current_address:
                if current_address in extras_set:
                    found_pairs.append((current_address, hx))
                else:
                    keys_to_post.append(hx)
                current_address = None
            continue
        parts = (line or "").strip().split()
        if len(parts) >= 2:
            addr = parts[0].strip()
            hx = _norm_hex(parts[1])
            if hx:
                if addr in extras_set:
                    found_pairs.append((addr, hx))
                else:
                    keys_to_post.append(hx)
        else:
            hx = _norm_hex((line or "").strip())
            if hx:
                keys_to_post.append(hx)
    return keys_to_post, found_pairs

def parse_vanity_v2(text, extras):
    extras_set = set([a for a in (extras or []) if isinstance(a, str)])
    keys_to_post = []
    found_pairs = []
    current_address = None
    lines = text.splitlines()
    i = 0
    hexset = set("0123456789abcdefABCDEF")
    while i < len(lines):
        line = lines[i]
        if "Pub Addr:" in line or "PubAddress:" in line or "Public Addr:" in line or "Public Address:" in line:
            try:
                if "Pub Addr:" in line:
                    token = "Pub Addr:"
                elif "PubAddress:" in line:
                    token = "PubAddress:"
                elif "Public Addr:" in line:
                    token = "Public Addr:"
                else:
                    token = "Public Address:"
                current_address = line.split(token, 1)[1].strip()
            except Exception:
                current_address = None
        elif "Priv (HEX):" in line:
            try:
                seg = line.split("Priv (HEX):", 1)[1]
            except Exception:
                seg = ""
            buf = seg.replace("0x", "")
            buf = "".join([c for c in buf if c in hexset])
            j = i + 1
            while len(buf) < 64 and j < len(lines):
                nxt = lines[j]
                buf += "".join([c for c in (nxt or "") if c in hexset])
                j += 1
            if len(buf) >= 64:
                hx = buf[:64].upper()
                if current_address:
                    if hx:
                        if current_address in extras_set:
                            found_pairs.append((current_address, hx))
                        else:
                            keys_to_post.append(hx)
                    current_address = None
                i = j - 1
        else:
            parts = (line or "").strip().split()
            if len(parts) >= 2:
                addr = parts[0].strip()
                hx = _norm_hex(parts[1])
                if hx:
                    if addr in extras_set:
                        found_pairs.append((addr, hx))
                    else:
                        keys_to_post.append(hx)
        i += 1
    return keys_to_post, found_pairs

def parse_bitcrack(text, extras):
    extras_set = set([a for a in (extras or []) if isinstance(a, str)])
    keys_to_post = []
    found_pairs = []
    for line in text.splitlines():
        parts = (line or "").strip().split()
        if len(parts) >= 2:
            addr = parts[0].strip()
            hx = _norm_hex(parts[1])
            if hx:
                if addr in extras_set:
                    found_pairs.append((addr, hx))
                else:
                    keys_to_post.append(hx)
        else:
            hx = _norm_hex((line or "").strip())
            if hx:
                keys_to_post.append(hx)
    return keys_to_post, found_pairs

def parse_out(text, kind, extras):
    k = (kind or "").lower()
    if "bitcrack" in k:
        return parse_bitcrack(text, extras)
    if "vanitysearch-v2" in k or k == "v2":
        return parse_vanity_v2(text, extras)
    return parse_vanity(text, extras)
