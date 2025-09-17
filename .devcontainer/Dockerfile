FROM ubuntu:22.04

# Avoid warnings by switching to noninteractive
ENV DEBIAN_FRONTEND=noninteractive

# Configure apt and install packages
RUN apt-get update \
    && apt-get -y install --no-install-recommends apt-utils dialog 2>&1 \
    && apt-get -y install \
        curl \
        git \
        git-lfs \
        vim \
        build-essential \
        ca-certificates \
        software-properties-common \
        gnupg \
        lsb-release \
        wget \
        unzip \
        sudo \
        openssh-client \
    # Create a non-root user
    && groupadd --gid 1000 vscode \
    && useradd --uid 1000 --gid vscode --shell /bin/bash --create-home vscode \
    && echo vscode ALL=\(root\) NOPASSWD:ALL > /etc/sudoers.d/vscode \
    && chmod 0440 /etc/sudoers.d/vscode \
    # Clean up
    && apt-get autoremove -y \
    && apt-get clean -y \
    && rm -rf /var/lib/apt/lists/*

# Switch back to dialog for any ad-hoc use of apt-get
ENV DEBIAN_FRONTEND=dialog

# Set the default user
USER vscode

# Set working directory
WORKDIR /workspaces/congressional-tech

# Create common directories
RUN mkdir -p /home/vscode/.cache/pip \
    && mkdir -p /home/vscode/.npm
