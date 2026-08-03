#!/bin/bash
# united-pool-gpu-script setup — continues on partial failures

REPO_URL="https://github.com/Miskecy/united-pool-gpu-script.git"
REPO_DIR="$HOME/united-pool-gpu-script"
CUDA_VERSION="12-1"
CUDA_HOME_PATH="/usr/local/cuda-12.1"

# ─── helpers ─────────────────────────────────────────────────────────────────

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

ERRORS=()

ok()   { echo -e "${GREEN}  [OK]${NC} $1"; }
warn() { echo -e "${YELLOW}  [WARN]${NC} $1"; ERRORS+=("WARN: $1"); }
fail() { echo -e "${RED}  [FAIL]${NC} $1"; ERRORS+=("FAIL: $1"); }

section() { echo -e "\n${GREEN}==>${NC} $1"; }

try() {
    # Usage: try "description" cmd arg arg ...
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
            || warn "CUDA repo dpkg/update failed — CUDA install will likely fail"
    else
        warn "Failed to download CUDA keyring — NVIDIA packages unavailable"
    fi
    rm -f "$TMP_DEB"
else
    ok "CUDA repository already present"
fi

# ─── 4. CUDA 12.1 ────────────────────────────────────────────────────────────

section "4. CUDA 12.1 (compiler + runtime)"
if command -v nvcc &>/dev/null && nvcc --version 2>/dev/null | grep -q "12\.1"; then
    ok "CUDA 12.1 already installed"
else
    sudo apt-get install -y \
        cuda-compiler-${CUDA_VERSION} \
        cuda-libraries-${CUDA_VERSION} \
        cuda-runtime-${CUDA_VERSION} \
        && ok "CUDA 12.1 installed" \
        || warn "CUDA 12.1 install failed — GPU mining binaries may not work"
fi

# ─── 5. CUDA environment variables ───────────────────────────────────────────

section "5. CUDA environment variables"
if [ -d "$CUDA_HOME_PATH" ]; then
    MARKER="# ==== CUDA 12.1 CONFIG (united-pool-gpu-script) ===="
    if ! grep -qF "$MARKER" ~/.bashrc 2>/dev/null; then
        # Remove any stale CUDA entries first
        sed -i '/CUDA 12\|cuda-12\|CUDA 13\|cuda-13/d' ~/.bashrc 2>/dev/null || true
        cat >> ~/.bashrc <<EOF

$MARKER
export CUDA_HOME=${CUDA_HOME_PATH}
export PATH=\$CUDA_HOME/bin:\$PATH
export LD_LIBRARY_PATH=\$CUDA_HOME/lib64:\${LD_LIBRARY_PATH:-}
EOF
        ok "CUDA env written to ~/.bashrc"
    else
        ok "CUDA env already in ~/.bashrc"
    fi
    export CUDA_HOME="$CUDA_HOME_PATH"
    export PATH="$CUDA_HOME/bin:$PATH"
    export LD_LIBRARY_PATH="$CUDA_HOME/lib64:${LD_LIBRARY_PATH:-}"

    # Register libs with the system linker so any session can find libcudart
    CUDA_LDCONF="/etc/ld.so.conf.d/cuda-12-1.conf"
    if [ ! -f "$CUDA_LDCONF" ]; then
        echo "$CUDA_HOME_PATH/lib64" | sudo tee "$CUDA_LDCONF" > /dev/null \
            && sudo ldconfig \
            && ok "CUDA libs registered with ldconfig" \
            || warn "ldconfig registration failed — set LD_LIBRARY_PATH manually before running script.py"
    else
        ok "CUDA ldconfig entry already present"
        sudo ldconfig 2>/dev/null || true
    fi
else
    warn "CUDA dir $CUDA_HOME_PATH not found — skipping env config"
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
    warn "nvidia-smi not found — GPU auto-detection in script.py will fall back to app -l"
fi

# ─── 7. Python dependencies ──────────────────────────────────────────────────

section "7. Python dependencies"
# Upgrade pip quietly; failure is non-fatal
python3 -m pip install --upgrade pip -q 2>/dev/null || warn "pip upgrade failed"

PYTHON_PKGS=(
    requests      # HTTP calls to pool API and Telegram
    colorama      # Colored terminal output
)

for pkg in "${PYTHON_PKGS[@]%%#*}"; do   # strip inline comments
    [[ -z "$pkg" ]] && continue
    if python3 -m pip install "$pkg" -q 2>/dev/null; then
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
echo "Run the miner with:"
echo "  cd $REPO_DIR && python3 script.py"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
