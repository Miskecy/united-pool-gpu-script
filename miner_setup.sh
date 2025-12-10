#!/bin/bash

# Ensure all commands are executed with superuser privileges
echo "Starting system update and dependencies installation..."

# 1. Update the local package index
sudo apt update

# 2. Install the specific CUDA Runtime Library for CUDA 11.0
# The -y flag confirms the installation without prompting
sudo apt install libcudart11.0 -y

# 3. Clone the Git repository
# This will create a new directory named 'united-pool-gpu-script'
echo "Cloning the repository..."
git clone https://github.com/Miskecy/united-pool-gpu-script
cd united-pool-gpu-script
chmod +x vanitysearch86.sh

echo "Setup complete. The repository has been cloned."