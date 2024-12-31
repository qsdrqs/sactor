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

## Usage

### Test Command in Sactor

The `test_command_path` option in the configuration file specifies the path that
contains the end-to-end test commands. It should be a json file with the following
format:

```json
[
    {
        "command": "command_to_run %t",
        "arbitrary_key": "arbitrary_value"
    },
    {
        "command": "command_to_run",
        "foo": "bar",
        "bar": ["foo", "bar"]
    },
    {
        "command": "command_to_run"
    },
    {
        "command": ["command_to_run", "%t"]
    }
    ...
]
```

Each item in the list is an end-to-end test command that will be run by Sactor.
The only required key is `command` for each test command. The `arbitrary_key` is
optional and can be arbitrary key-value pairs can be added to the test command.

Command is executed in the same working directory where the json file is located.
