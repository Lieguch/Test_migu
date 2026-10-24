FROM mcr.microsoft.com/devcontainers/base:ubuntu-22.04

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends \
    build-essential \
    ninja-build \
    pkg-config \
    python3 \
    python3-pip \
    libglib2.0-dev \
    libpixman-1-dev \
    git \
    curl \
    ca-certificates \
    ca-certificates \
    wget \
    xz-utils \
    flex \
    bison \
    libssl-dev \
    libncurses5-dev \
    bc \
    gcc-aarch64-linux-gnu \
    gcc-arm-none-eabi \
    qemu-system-arm \
    qemu-utils \
    device-tree-compiler \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace
