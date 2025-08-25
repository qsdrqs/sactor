FROM debian:bullseye-slim

# Avoid interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive

# Install essential build tools and dependencies
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

# Install Rust via rustup
ENV RUSTUP_HOME=/usr/local/rustup \
    CARGO_HOME=/usr/local/cargo \
    PATH=/usr/local/cargo/bin:$PATH
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain 1.89 --profile minimal

# Install C2Rust from source (pinned to v0.20.0)
RUN cargo install c2rust --version 0.20.0

# Install Crown fork from sactor branch
RUN git clone -b sactor https://github.com/qsdrqs/crown.git /opt/crown && \
    cd /opt/crown && \
    cargo build --release && \
    ln -s /opt/crown/target/release/crown /usr/local/bin/crown

# Install the standalone uv binary
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH=/root/.local/bin:$PATH

# Install Python 3.12
RUN uv python install 3.12

# Set up virtual environment with Python 3.12
ENV VIRTUAL_ENV=/opt/venv
RUN mkdir -p /opt/venv
RUN uv venv $VIRTUAL_ENV --python 3.12
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Set up the application directory
WORKDIR /app
COPY . .

# Install Python dependencies using uv
RUN uv pip install -e .

# Set the entrypoint for the application
ENTRYPOINT ["/opt/venv/bin/sactor"]
