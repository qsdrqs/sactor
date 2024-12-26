# SACToR: Structure-Aware C to Rust Translator

## Introduction

SACToR is a tool that translates C code to Rust code through Large Language
Models (LLMs). It is designed to be used in the context of a larger project that
aims to provide a safe and efficient way to write system software. The goal of
SACToR is to provide a way to translate existing C code to Rust code, and gain
the benefits of Rust's safety and performance guarantees.

## Requirements

- Python 3.8 or later
- rustup
- poetry (Python package manager)

- c2rust
- crown

## Installation
1. Install `rust_ast_parser`
2. Install `sactor`

## Configuration

The default configuration is located in `config.default.yaml`. To customize the
configuration, create a `config.yaml` file in the same directory. Alternatively,
you can specify a custom configuration file path by using the `-c` or `--config`
option with the `sactor` command.
