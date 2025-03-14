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

Several examples are provided in the (c_example directory)[https://github.com/qsdrqs/sactor/tree/main/tests/c_examples].

### Command Line Interface

Sactor provides a command line interface (CLI) for running the translation and
testing processes. The main command is `sactor`, which has several subcommands:

- `run-tests`: Runs end-to-end tests on the translation process.
- `generate-tests`: Generates test commands based on the provided test samples.
- `translate`: Translates C code to Rust code using the specified translation
  method.

Example usage:

```bash
sactor translate /path/to/c /path/to/test_task.json -r /path/to/result/ --type bin
```
This command translates the C code located at `/path/to/c` using the test
task specified in `/path/to/test_task.json`, and saves the result to
`/path/to/result/`. The `--type` option specifies the type of the binary (e.g.,
`bin`, `lib`). The `-r` option specifies the path to save the translation result.

Sactor also implements a *test generator* that generates test commands based on
the provided C code and test samples to provide more end-to-end testing
capabilities. The test generator can be run using the `generate-tests` subcommand.

```bash
sactor generate-tests /path/to/c 10 --type bin --executable /path/to/executable
```
In this example, `10` is the number of test commands to generate. The
`--type` option specifies the type of the binary (e.g., `bin`, `lib`), and
`--executable` specifies the path to the executable of the C code that is
required for generating the end-to-end tests.

### Test Task in `sactor translate`

The `test_task_path` option in the configuration file specifies the path that
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

`%t` is a placeholder that will be replaced with the path to the testing target
executable.

Command is executed in the same working directory where the json file is located.

### Test Samples in `sactor generate-tests`

The `test_samples_path` option in the configuration file specifies the path that
contains the test samples to be used for generating test commands. It should be
a json file with the following format:

```json
[
    {
        "input": "a b \n c d",
        "output": "c d \n a b"
    }
    ...
]
```

Each item in the list is a test sample that will be used to generate test commands.
"input" is the input to the test command, and "output" is the expected output of
the test command. Only "input" is required for each test sample. "output" is optional
and will not be used for generating tests.
