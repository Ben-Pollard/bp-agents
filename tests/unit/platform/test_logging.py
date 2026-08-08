import logging
import os

from bp_agents.platform.runner import setup_logging


def test_setup_logging_default_level() -> None:
    root = logging.getLogger()
    saved_level = root.level
    saved_handlers = root.handlers.copy()
    saved_handlers_len = len(root.handlers)

    try:
        root.handlers.clear()
        root.setLevel(logging.WARNING)

        if "BP_LOG_LEVEL" in os.environ:
            del os.environ["BP_LOG_LEVEL"]

        setup_logging()
        assert root.level == logging.INFO
        assert len(root.handlers) >= 1
    finally:
        root.setLevel(saved_level)
        root.handlers.clear()
        root.handlers.extend(saved_handlers)


def test_setup_logging_overrides_existing_handlers() -> None:
    root = logging.getLogger()
    saved_level = root.level
    saved_handlers = root.handlers.copy()

    try:
        root.handlers.clear()
        root.setLevel(logging.WARNING)
        root.addHandler(logging.StreamHandler())

        os.environ["BP_LOG_LEVEL"] = "debug"
        setup_logging()
        assert root.level == logging.DEBUG
    finally:
        root.setLevel(saved_level)
        root.handlers.clear()
        root.handlers.extend(saved_handlers)
        if "BP_LOG_LEVEL" in os.environ:
            del os.environ["BP_LOG_LEVEL"]


def test_setup_logging_uses_custom_format() -> None:
    root = logging.getLogger()
    saved_level = root.level
    saved_handlers = root.handlers.copy()

    try:
        root.handlers.clear()
        root.setLevel(logging.WARNING)

        os.environ["BP_LOG_LEVEL"] = "debug"
        setup_logging()

        assert root.level == logging.DEBUG
        handler = root.handlers[0]
        fmt = handler.formatter._fmt
        assert "%(asctime)s" in fmt
        assert "%(levelname)s" in fmt
    finally:
        root.setLevel(saved_level)
        root.handlers.clear()
        root.handlers.extend(saved_handlers)
        if "BP_LOG_LEVEL" in os.environ:
            del os.environ["BP_LOG_LEVEL"]
