#!/usr/bin/env bash
# Create the conda env of the analysis (Grounded-SAM-2 + every analysis step) and download the model weights.
# Usage, from the repo root:  bash envs/install.sh [phenotyping|weights]   (default: both)
# Needs conda, git, a CUDA 12.8 toolkit (nvcc, CUDA_HOME) and an NVIDIA GPU.
# Versions are those the pipeline was validated with (Python 3.10, torch 2.7.0+cu128).
set -euo pipefail
cd "$(dirname "$0")/.."
REPO=$PWD
TORCH="torch==2.7.0 torchvision==0.22.0 --index-url https://download.pytorch.org/whl/cu128"
# GPU architecture the Grounding DINO CUDA extension is compiled for (8.9 = RTX 40xx); override for another GPU
export TORCH_CUDA_ARCH_LIST="${TORCH_CUDA_ARCH_LIST:-8.9}"
export PYTHONNOUSERSITE=1  # packages in ~/.local must not leak into the envs
eval "$(conda shell.bash hook)"
git submodule update --init --recursive

install_phenotyping() {
    conda create -y -n phenotyping python=3.10
    conda activate phenotyping
    pip install $TORCH
    cd "$REPO/third_party/Grounded-SAM-2"
    SAM2_BUILD_ALLOW_ERRORS=0 pip install -e .
    pip install --no-build-isolation -e grounding_dino
    pip install transformers==4.38.2 supervision==0.28.0 pycocotools opencv-python scipy matplotlib pillow pytest
    conda deactivate
}

download_weights() {
    (cd "$REPO/third_party/Grounded-SAM-2/checkpoints" && bash download_ckpts.sh)
    (cd "$REPO/third_party/Grounded-SAM-2/gdino_checkpoints" && bash download_ckpts.sh)
}

case "${1:-all}" in
    phenotyping) install_phenotyping ;;
    weights) download_weights ;;
    all) install_phenotyping; download_weights ;;
    *) echo "unknown target: $1" >&2; exit 1 ;;
esac
