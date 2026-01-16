#!/bin/bash
set -e

echo "🚀 Starting CUDA 12.1 environment setup for united-pool-gpu-script"

# ----------------------------
# 1. Update system
# ----------------------------
sudo apt update

# ----------------------------
# 2. Base dependencies
# ----------------------------
sudo apt install -y \
    build-essential \
    git \
    python3 \
    python3-pip \
    wget \
    ca-certificates

# ----------------------------
# 3. Add NVIDIA CUDA repository (if missing)
# ----------------------------
if [ ! -f /etc/apt/sources.list.d/cuda.list ]; then
    echo "📦 Adding NVIDIA CUDA repository"
    wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/x86_64/cuda-keyring_1.1-1_all.deb
    sudo dpkg -i cuda-keyring_1.1-1_all.deb
    sudo apt update
fi

# ----------------------------
# 4. Install CUDA 12.1 (NO Nsight)
# ----------------------------
echo "⚙️ Installing CUDA 12.1 (compiler + runtime only)"

sudo apt install -y \
    cuda-compiler-12-1 \
    cuda-libraries-12-1 \
    cuda-runtime-12-1

# ----------------------------
# 5. Configure CUDA environment (bashrc)
# ----------------------------
echo "🧩 Configuring CUDA 12.1 environment variables"

CUDA_BLOCK='
# ==== CUDA 12.1 CONFIG (united-pool-gpu-script) ====
export CUDA_HOME=/usr/local/cuda-12.1
export PATH=$CUDA_HOME/bin:$PATH
export LD_LIBRARY_PATH=$CUDA_HOME/lib64:$LD_LIBRARY_PATH
'

# Remove old CUDA entries to avoid conflicts
sed -i '/CUDA 12/d;/cuda-12/d;/CUDA 13/d;/cuda-13/d' ~/.bashrc

# Append clean CUDA config
echo "$CUDA_BLOCK" >> ~/.bashrc

# Apply immediately for this session
source ~/.bashrc

# ----------------------------
# 6. Verify CUDA
# ----------------------------
echo "🔍 Verifying CUDA installation"
nvcc -V

# ----------------------------
# 7. Python dependencies
# ----------------------------
echo "🐍 Installing Python dependencies"
pip3 install --upgrade pip
pip3 install requests colorama

# ----------------------------
# 8. Clone repository
# ----------------------------
echo "📥 Cloning united-pool-gpu-script repository"

if [ ! -d "$HOME/united-pool-gpu-script" ]; then
    git clone https://github.com/Miskecy/united-pool-gpu-script.git "$HOME/united-pool-gpu-script"
else
    echo "Repository already exists, skipping clone"
fi

cd "$HOME/united-pool-gpu-script"

# ----------------------------
# 9. Set permissions on binaries
# ----------------------------
echo "🔑 Setting execute permissions on bin/"
chmod +x ./bin/* || true

echo "✅ Setup complete. united-pool-gpu-script is ready to run."
