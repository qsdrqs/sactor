import argparse

import pytest

from sactor import __main__ as cli


@pytest.fixture
def translate_parser():
    parser = argparse.ArgumentParser()
    cli.parse_translate(parser)
    return parser


@pytest.fixture
def minimal_config():
    return {"general": {"timeout_seconds": 1}}


def _run_translate(monkeypatch, translate_parser, minimal_config, argv):
    captured = {}

    monkeypatch.setattr(cli.utils, "try_load_config", lambda _: minimal_config)
    monkeypatch.setattr(cli, "_configure_logging_from_args", lambda *args, **kwargs: None)

    class DummySactor:
        @classmethod
        def translate(cls, *, executable_object, **kwargs):
            captured["value"] = executable_object
            class _R:
                any_failed = False
            return _R()

    monkeypatch.setattr(cli, "Sactor", DummySactor)

    args = translate_parser.parse_args(argv)
    cli.translate(translate_parser, args)
    return captured["value"]


def test_translate_single_executable_object(monkeypatch, translate_parser, minimal_config):
    argv = [
        "input.c",
        "tests/verifier/test_cmd.json",
        "--type",
        "lib",
        "--executable-object",
        "test1.o",
    ]
    value = _run_translate(monkeypatch, translate_parser, minimal_config, argv)
    assert value == "test1.o"


def test_translate_multiple_executable_objects(monkeypatch, translate_parser, minimal_config):
    argv = [
        "input.c",
        "tests/verifier/test_cmd.json",
        "--type",
        "lib",
        "--executable-object",
        "test1.o",
        "--executable-object",
        "test2.o",
    ]
    value = _run_translate(monkeypatch, translate_parser, minimal_config, argv)
    assert value == ["test1.o", "test2.o"]
