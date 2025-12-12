#!/bin/bash

# Ensure all commands are executed with superuser privileges
echo "Starting system update and dependencies installation..."

#wget https://developer.download.nvidia.com/compute/cuda/repos/wsl-ubuntu/x86_64/cuda-keyring_1.1-1_all.deb
#sudo dpkg -i cuda-keyring_1.1-1_all.deb

# 1. Update the local package index
sudo apt update

# 2. Install the specific CUDA Runtime Library for CUDA 11.0
# The -y flag confirms the installation without prompting
sudo apt install libcudart11.0 -y

sudo apt install cuda-toolkit-12-1 -y
# Configuração CUDA 12.1 (Exemplo)
#export PATH=/usr/local/cuda-12.1/bin:$PATH
#export LD_LIBRARY_PATH=/usr/local/cuda-12.1/lib64:$LD_LIBRARY_PATH
#source ~/.bashrc
nvcc -V

sudo chmod +x ./bin/*

echo "Setup complete. The repository has been cloned."