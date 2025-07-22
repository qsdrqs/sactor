FROM debian:bullseye-slim

# Avoid interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive

# 1. Install essential build tools and dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    pkg-config \
    libssl-dev \
    ca-certificates \
    git \
    cmake \
    clang \
    libclang-dev \
    llvm-dev \
    valgrind && \
    rm -rf /var/lib/apt/lists/*

# 2. Install Rust via rustup
ENV RUSTUP_HOME=/usr/local/rustup \
    CARGO_HOME=/usr/local/cargo \
    PATH=/usr/local/cargo/bin:$PATH
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain 1.78 --profile minimal

# Install C2Rust from source (pinned to v0.20.0)
RUN git clone https://github.com/immunant/c2rust.git /tmp/c2rust && \
    cd /tmp/c2rust && \
    git checkout v0.20.0 && \
    cargo build --release && \
    find target/release -maxdepth 1 -type f -executable -exec cp {} /usr/local/bin/ \; && \
    rm -rf /tmp/c2rust

# Install Crown fork from sactor branch
RUN git clone -b sactor https://github.com/qsdrqs/crown.git /tmp/crown && \
    cd /tmp/crown && \
    cargo build --release && \
    find target/release -maxdepth 1 -type f -executable -exec cp {} /usr/local/bin/ \; && \
    rm -rf /tmp/crown

# 3. Create application user early
RUN groupadd -r sactor && useradd -r -g sactor -u 1001 -m sactor

# 4. Install the standalone uv binary as sactor user
USER sactor
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH=/home/sactor/.local/bin:$PATH

# 5. Install Python 3.12
RUN uv python install 3.12

# 6. Set up virtual environment with Python 3.12
ENV VIRTUAL_ENV=/opt/venv
USER root
RUN mkdir -p /opt/venv && chown sactor:sactor /opt/venv
USER sactor
RUN uv venv $VIRTUAL_ENV --python 3.12
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# 7. Set up the application directory
USER root
WORKDIR /app
COPY . .
RUN chown -R sactor:sactor /app

# 8. Install Python dependencies using uv
USER root
RUN chown -R sactor:sactor /usr/local/rustup /usr/local/cargo
USER sactor
RUN uv pip install -e .

# Set the entrypoint for the application
ENTRYPOINT ["/opt/venv/bin/sactor"]
