from collections.abc import Generator

import httpx
import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--no-auto-compose",
        action="store_true",
        default=False,
        help="Skip auto-start of docker compose services for e2e tests",
    )


def _compose_up(services: list[str]) -> None:
    import subprocess

    subprocess.run(
        ["docker", "compose", "up", "-d", "--wait"] + services,
        check=True,
        capture_output=True,
    )


def _compose_run(service: str) -> None:
    import subprocess

    subprocess.run(
        ["docker", "compose", "run", "--rm", service],
        check=True,
        capture_output=True,
    )


def _compose_down() -> None:
    import subprocess

    subprocess.run(
        ["docker", "compose", "down", "-t", "5"],
        check=False,
        capture_output=True,
    )


def _wait_for_http(url: str, timeout: float = 60.0) -> None:
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            r = httpx.get(url, timeout=5)
            if r.status_code < 500:
                return
        except Exception:
            pass
        time.sleep(1)
    raise RuntimeError(f"{url} did not become ready within {timeout}s")


@pytest.fixture(scope="session")
def redmine_compose(request: pytest.FixtureRequest) -> Generator[None, None, None]:
    if request.config.getoption("--no-auto-compose"):
        yield
        return
    _compose_up(["redmine-db", "redmine"])
    _wait_for_http("http://localhost:8082/")
    _compose_run("redmine-setup")
    yield
    _compose_down()


@pytest.fixture(scope="session")
def egress_compose(request: pytest.FixtureRequest) -> Generator[None, None, None]:
    if request.config.getoption("--no-auto-compose"):
        yield
        return
    _compose_up(["egress-proxy"])
    yield
    _compose_down()
