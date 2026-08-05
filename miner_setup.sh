#!/bin/bash
# united-pool-gpu-script setup — continues on partial failures

REPO_URL="https://github.com/Miskecy/united-pool-gpu-script.git"
REPO_DIR="$HOME/united-pool-gpu-script"

# ─── helpers ─────────────────────────────────────────────────────────────────

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

ERRORS=()

ok()   { echo -e "${GREEN}  [OK]${NC} $1"; }
warn() { echo -e "${YELLOW}  [WARN]${NC} $1"; ERRORS+=("WARN: $1"); }
fail() { echo -e "${RED}  [FAIL]${NC} $1"; ERRORS+=("FAIL: $1"); }

section() { echo -e "\n${GREEN}==>${NC} $1"; }

try() {
    local desc="$1"; shift
    if "$@" 2>/dev/null; then
        ok "$desc"
        return 0
    else
        fail "$desc"
        return 1
    fi
}

# ─── 1. System update ────────────────────────────────────────────────────────

section "1. System update"
sudo apt-get update -qq || warn "apt update failed — continuing with cached index"

# ─── 2. Base dependencies ────────────────────────────────────────────────────

section "2. Base dependencies"
sudo apt-get install -y \
    build-essential \
    git \
    python3 \
    python3-pip \
    wget \
    curl \
    ca-certificates \
    || warn "Some base packages failed to install"

# ─── 3. NVIDIA CUDA repository ───────────────────────────────────────────────

section "3. NVIDIA CUDA repository"
if [ ! -f /etc/apt/sources.list.d/cuda-ubuntu2204-x86_64.list ] && \
   [ ! -f /etc/apt/sources.list.d/cuda.list ]; then
    echo "  Adding NVIDIA CUDA repository..."
    TMP_DEB=$(mktemp --suffix=.deb)
    if wget -q -O "$TMP_DEB" \
        "https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/x86_64/cuda-keyring_1.1-1_all.deb"; then
        sudo dpkg -i "$TMP_DEB" && sudo apt-get update -qq \
            && ok "CUDA repository added" \
            || warn "CUDA repo dpkg/update failed"
    else
        warn "Failed to download CUDA keyring — NVIDIA packages unavailable"
    fi
    rm -f "$TMP_DEB"
else
    ok "CUDA repository already present"
fi

# ─── 4. CUDA installation ────────────────────────────────────────────────────

section "4. CUDA (compiler + runtime)"
if command -v nvcc &>/dev/null; then
    CUDA_VER=$(nvcc --version 2>/dev/null | grep -oP "release \K[0-9]+\.[0-9]+")
    ok "CUDA ${CUDA_VER} already installed — skipping install"
else
    echo "  No nvcc found. Trying to install CUDA 12.8..."
    sudo apt-get install -y \
        cuda-compiler-12-8 \
        cuda-libraries-12-8 \
        cuda-runtime-12-8 \
        && ok "CUDA 12.8 installed" \
        || warn "CUDA install failed — if your driver is newer than 570, install the matching CUDA version manually"
fi

# ─── 5. CUDA environment variables ───────────────────────────────────────────

section "5. CUDA environment variables"

# Auto-detect CUDA home: prefer path from nvcc binary, then scan /usr/local
CUDA_HOME_PATH=""
if command -v nvcc &>/dev/null; then
    NVCC_BIN=$(command -v nvcc)
    CUDA_HOME_PATH=$(dirname "$(dirname "$NVCC_BIN")")
fi
if [ -z "$CUDA_HOME_PATH" ] || [ ! -d "$CUDA_HOME_PATH" ]; then
    for d in /usr/local/cuda-13.2 /usr/local/cuda-13.1 /usr/local/cuda-13.0 \
              /usr/local/cuda-12.8 /usr/local/cuda-12.6 /usr/local/cuda-12.4 \
              /usr/local/cuda; do
        if [ -d "$d" ]; then
            CUDA_HOME_PATH="$d"
            break
        fi
    done
fi

if [ -n "$CUDA_HOME_PATH" ] && [ -d "$CUDA_HOME_PATH" ]; then
    CUDA_LABEL=$(basename "$CUDA_HOME_PATH")   # e.g. cuda-13.2
    MARKER="# ==== CUDA CONFIG (united-pool-gpu-script) ===="

    if ! grep -qF "$MARKER" ~/.bashrc 2>/dev/null; then
        # Remove stale entries from any previous run of this script
        sed -i '/CUDA CONFIG (united-pool-gpu-script)/,+4d' ~/.bashrc 2>/dev/null || true
        cat >> ~/.bashrc <<EOF

$MARKER
export CUDA_HOME=${CUDA_HOME_PATH}
export PATH=\$CUDA_HOME/bin:\$PATH
export LD_LIBRARY_PATH=\$CUDA_HOME/lib64:\${LD_LIBRARY_PATH:-}
EOF
        ok "CUDA env written to ~/.bashrc (${CUDA_LABEL})"
    else
        ok "CUDA env already in ~/.bashrc"
    fi

    export CUDA_HOME="$CUDA_HOME_PATH"
    export PATH="$CUDA_HOME/bin:$PATH"
    export LD_LIBRARY_PATH="$CUDA_HOME/lib64:${LD_LIBRARY_PATH:-}"

    # Register libs with system linker — use a version-neutral conf name
    CUDA_LDCONF="/etc/ld.so.conf.d/cuda-united-pool.conf"
    # Remove stale confs from previous versions of this script
    sudo rm -f /etc/ld.so.conf.d/cuda-12-1.conf \
               /etc/ld.so.conf.d/cuda-12-8.conf 2>/dev/null || true
    if [ ! -f "$CUDA_LDCONF" ] || ! grep -qF "$CUDA_HOME_PATH" "$CUDA_LDCONF" 2>/dev/null; then
        echo "$CUDA_HOME_PATH/lib64" | sudo tee "$CUDA_LDCONF" > /dev/null \
            && sudo ldconfig \
            && ok "CUDA libs registered with ldconfig" \
            || warn "ldconfig failed — set LD_LIBRARY_PATH manually if needed"
    else
        ok "CUDA ldconfig entry already present"
        sudo ldconfig 2>/dev/null || true
    fi
else
    warn "No CUDA installation found — skipping env config"
fi

# ─── 6. Verify CUDA ──────────────────────────────────────────────────────────

section "6. CUDA verification"
if command -v nvcc &>/dev/null; then
    nvcc --version
    ok "nvcc found"
else
    warn "nvcc not in PATH — CUDA may not be installed or needs a new shell"
fi

if command -v nvidia-smi &>/dev/null; then
    nvidia-smi --query-gpu=index,name --format=csv,noheader 2>/dev/null \
        && ok "nvidia-smi GPU list OK" \
        || warn "nvidia-smi found but failed to query GPUs"
else
    warn "nvidia-smi not found — GPU auto-detection will fall back to app -l"
fi

# ─── 7. Python dependencies ──────────────────────────────────────────────────

section "7. Python dependencies"
python3 -m pip install --upgrade pip -q 2>/dev/null \
    || python3 -m pip install --upgrade pip -q --break-system-packages 2>/dev/null \
    || warn "pip upgrade failed"

PYTHON_PKGS=(
    requests      # HTTP calls to pool API and Telegram
    colorama      # Colored terminal output
    flask         # Web dashboard (dashboard.py)
    werkzeug      # Flask dependency — HTTP utilities
)

for pkg in "${PYTHON_PKGS[@]%%#*}"; do
    [[ -z "$pkg" ]] && continue
    if python3 -m pip install "$pkg" -q 2>/dev/null; then
        ok "pip: $pkg"
    elif python3 -m pip install "$pkg" -q --break-system-packages 2>/dev/null; then
        ok "pip: $pkg"
    else
        fail "pip: $pkg — install failed"
    fi
done

# ─── 8. Clone / update repository ────────────────────────────────────────────

section "8. Repository"
if [ ! -d "$REPO_DIR" ]; then
    if git clone "$REPO_URL" "$REPO_DIR"; then
        ok "Cloned to $REPO_DIR"
    else
        fail "git clone failed"
    fi
else
    ok "Repository already exists at $REPO_DIR"
    cd "$REPO_DIR"
    git pull --ff-only 2>/dev/null && ok "Repository updated" || warn "git pull failed — using existing files"
fi

# ─── 9. Binary permissions ───────────────────────────────────────────────────

section "9. Binary permissions"
BIN_DIR="$REPO_DIR/bin"
if [ -d "$BIN_DIR" ]; then
    FOUND=0
    while IFS= read -r -d '' f; do
        chmod +x "$f" && FOUND=$((FOUND + 1))
    done < <(find "$BIN_DIR" -maxdepth 1 -type f -print0 2>/dev/null)
    [ "$FOUND" -gt 0 ] && ok "$FOUND binary/binaries marked executable in bin/" \
                       || warn "bin/ is empty — place your VanitySearch/BitCrack builds there"
else
    warn "bin/ directory not found in $REPO_DIR — create it and add your GPU binaries"
fi

# ─── Summary ─────────────────────────────────────────────────────────────────

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [ ${#ERRORS[@]} -eq 0 ]; then
    echo -e "${GREEN}Setup complete — no errors.${NC}"
else
    echo -e "${YELLOW}Setup finished with ${#ERRORS[@]} warning(s)/error(s):${NC}"
    for e in "${ERRORS[@]}"; do
        echo -e "  ${YELLOW}•${NC} $e"
    done
fi
echo ""
echo "Run the miner:"
echo "  cd $REPO_DIR"
echo "  bash miner.sh start          # background (miner + dashboard)"
echo ""
echo "Run the web dashboard:"
echo "  python3 dashboard.py         # access at http://YOUR_IP:8080"
echo "  (optional) add \"dashboard_password\" to settings.json to require login"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
