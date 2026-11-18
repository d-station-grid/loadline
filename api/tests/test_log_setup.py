import logging

import pytest

from app.core.log_setup import APP_LOGGER, configure_logging
from app.main import create_app


def test_app_info_logs_reach_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    """本番で dispatch の人数などが見えるよう、app.* の info を stdout に出す。"""
    create_app()

    logging.getLogger("app.services.auto_reviews").info("dispatch: enqueued %d of %d users", 1, 2)
    logging.getLogger("app.services.auto_reviews").debug("not shown")

    out = capsys.readouterr().out
    assert "INFO app.services.auto_reviews: dispatch: enqueued 1 of 2 users" in out
    assert "not shown" not in out


def test_configuring_twice_adds_one_handler() -> None:
    configure_logging()
    configure_logging()
    create_app()

    assert len(logging.getLogger(APP_LOGGER).handlers) == 1


def test_app_logs_still_reach_caplog(caplog: pytest.LogCaptureFixture) -> None:
    """親のロガーへも渡すので、caplog で確かめるテストはそのまま動く。"""
    configure_logging()

    with caplog.at_level(logging.INFO):
        logging.getLogger("app.adapters.cloud_tasks").info("tasks: queued")

    assert "tasks: queued" in caplog.text
