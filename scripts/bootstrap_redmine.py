"""Bootstrap Redmine for first-time setup.

Creates admin user, generates API key, creates project, and writes .env.
Idempotent — skips any resource that already exists.

Usage:
    uv run python scripts/bootstrap_redmine.py

Environment variables:
    REDMINE_URL       -- base URL (default: http://localhost:8082)
    ADMIN_LOGIN       -- Redmine admin login (default: admin)
    ADMIN_PASSWORD    -- Redmine admin password (default: admin)
    BP_ADMIN_EMAIL    -- email for admin user (default: admin@bp-agents.local)
    BP_PROJECT_NAME   -- project name (default: default)
    BP_PROJECT_ID     -- project identifier (default: default)
"""

import json
import logging
import os
import sys
import time

import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("bootstrap_redmine")

REDMINE_URL = os.getenv("REDMINE_URL", "http://localhost:8082")
ADMIN_LOGIN = os.getenv("ADMIN_LOGIN", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")
BP_ADMIN_EMAIL = os.getenv("BP_ADMIN_EMAIL", "admin@bp-agents.local")
BP_PROJECT_NAME = os.getenv("BP_PROJECT_NAME", "default")
BP_PROJECT_ID = os.getenv("BP_PROJECT_ID", "default")

AUTH = (ADMIN_LOGIN, ADMIN_PASSWORD)


def _wait_for_redmine(timeout: int = 120) -> None:
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = httpx.get(f"{REDMINE_URL}/", timeout=5)
            logger.info("Redmine ready (status %s)", r.status_code)
            return
        except httpx.HTTPError:
            logger.info("Waiting for Redmine...")
            time.sleep(2)
    raise RuntimeError("Redmine did not become ready")


def _admin_exists() -> bool:
    r = httpx.get(
        f"{REDMINE_URL}/users.json",
        auth=AUTH,
        headers={"Content-Type": "application/json"},
    )
    if r.status_code == 422:
        return False
    r.raise_for_status()
    users = r.json().get("users", [])
    return any(u.get("login") == ADMIN_LOGIN for u in users)


def _get_admin_api_key() -> str:
    r = httpx.get(
        f"{REDMINE_URL}/users/current.json?include=api_key",
        auth=AUTH,
        headers={"Content-Type": "application/json"},
    )
    if r.status_code == 403:
        logger.info("API auth not ready yet — admin user may need password reset")
        return ""
    r.raise_for_status()
    api_key = r.json().get("user", {}).get("api_key")
    if not api_key:
        user_id = r.json().get("user", {}).get("id")
        put_r = httpx.put(
            f"{REDMINE_URL}/users/{user_id}.json",
            auth=AUTH,
            headers={"Content-Type": "application/json"},
            json={"user": {"generate_password": False}},
        )
        put_r.raise_for_status()
        get_r = httpx.get(
            f"{REDMINE_URL}/users/{user_id}.json?include=api_key",
            auth=AUTH,
            headers={"Content-Type": "application/json"},
        )
        get_r.raise_for_status()
        api_key = get_r.json().get("user", {}).get("api_key", "")
    return api_key


def _enable_api_and_create_statuses() -> None:
    import docker as docker_sdk

    container_name = os.getenv("REDMINE_CONTAINER", "bp-agents-redmine-1")
    client = docker_sdk.from_env()
    container = client.containers.get(container_name)

    enable_api_code = (
        "Setting.rest_api_enabled = '1'; "
        "Setting.login_required = '0'; "
        "puts 'API_ENABLED:ok'"
    )
    container.exec_run(
        ["bundle", "exec", "rails", "runner", enable_api_code],
        workdir="/usr/src/redmine",
    )

    from bp_agents.workflows.sdd.contracts import TicketState

    statuses_lines = ["existing = IssueStatus.all.map(&:name).to_set"]
    for s in TicketState:
        is_closed = "true" if s.value in ("done", "blocked") else "false"
        statuses_lines.append(
            f"unless existing.include?('{s.value}'); "
            f"IssueStatus.create!(name: '{s.value}', is_closed: {is_closed}); "
            f"end"
        )
    statuses_lines.append(
        "IssueStatus.all.each { |s| puts 'STATUS:' + s.id.to_s + ':' + s.name }"
    )
    statuses_code = "; ".join(statuses_lines)
    container.exec_run(
        ["bundle", "exec", "rails", "runner", statuses_code],
        workdir="/usr/src/redmine",
    )
    logger.info("Settings enabled and statuses created via Rails runner")


def _prepare_admin_via_rails() -> str:
    logger.info("Preparing admin user via Rails runner...")
    import docker as docker_sdk

    container_name = os.getenv("REDMINE_CONTAINER", "bp-agents-redmine-1")
    client = docker_sdk.from_env()
    container = client.containers.get(container_name)

    rails_code = (
        "u = User.find_by_login('admin'); "
        "u.must_change_passwd = false; "
        "u.save!; "
        "token = u.api_token; "
        "if token.nil?; "
        "  Token.create!(user_id: u.id, action: 'api'); "
        "  token = u.reload.api_token; "
        "end; "
        "puts 'API_KEY:' + token.value"
    )
    exit_code, output = container.exec_run(
        ["bundle", "exec", "rails", "runner", rails_code],
        workdir="/usr/src/redmine",
    )
    if exit_code != 0:
        logger.error("Admin prep Rails runner failed: %s", output.decode())
        return ""

    _enable_api_and_create_statuses()

    for line in output.decode().strip().splitlines():
        line = line.strip()
        if line.startswith("API_KEY:"):
            api_key = line.split(":", 1)[1].strip()
            logger.info("Admin API key obtained via Rails runner")
            return api_key
    logger.error("No API_KEY in output: %s", output.decode())
    return ""


def _ensure_project_exists(api_key: str) -> int:
    headers = {
        "X-Redmine-API-Key": api_key,
        "Content-Type": "application/json",
    }
    r = httpx.get(
        f"{REDMINE_URL}/projects/{BP_PROJECT_ID}.json",
        headers=headers,
    )
    if r.status_code == 200:
        logger.info("Project '%s' already exists", BP_PROJECT_NAME)
        return r.json()["project"]["id"]
    r = httpx.post(
        f"{REDMINE_URL}/projects.json",
        headers=headers,
        json={
            "project": {
                "name": BP_PROJECT_NAME,
                "identifier": BP_PROJECT_ID,
                "is_public": True,
            }
        },
    )
    if r.status_code == 201:
        project_id = r.json()["project"]["id"]
        logger.info("Created project '%s' (id=%s)", BP_PROJECT_NAME, project_id)
        return project_id
    if r.status_code == 422:
        logger.info("Project '%s' already exists (validation)", BP_PROJECT_NAME)
        list_r = httpx.get(
            f"{REDMINE_URL}/projects.json",
            headers=headers,
        )
        list_r.raise_for_status()
        for proj in list_r.json().get("projects", []):
            if proj.get("identifier") == BP_PROJECT_ID:
                return proj["id"]
    r.raise_for_status()
    return 0


def _ensure_issue_statuses(api_key: str) -> dict[str, int]:
    from bp_agents.workflows.sdd.contracts import TicketState

    headers = {
        "X-Redmine-API-Key": api_key,
        "Content-Type": "application/json",
    }
    r = httpx.get(f"{REDMINE_URL}/issue_statuses.json", headers=headers)
    r.raise_for_status()
    existing = {s["name"]: s for s in r.json().get("issue_statuses", [])}

    status_map = {
        name: s["id"]
        for name, s in existing.items()
        if name in TicketState._value2member_map_
    }
    logger.info("Status map: %s", json.dumps(status_map))
    return status_map


def _write_env(api_key: str) -> None:
    env_path = os.getenv("BP_ENV_OUTPUT", ".env")
    env_vars = {
        "REDMINE_BASE_URL": "http://redmine:3000",
        "REDMINE_API_KEY": api_key,
        "REDMINE_PROJECT": BP_PROJECT_ID,
        "EGRESS_PROXY_URL": "http://egress-proxy:8080",
        "BP_POLL_INTERVAL": "5",
        "BP_SANDBOX_IMAGE": os.getenv("BP_SANDBOX_IMAGE", "opencode-agent:latest"),
        "BP_TARGET_REPO_PATH": os.getenv(
            "BP_TARGET_REPO_PATH", "/data/repos/default-project"
        ),
        "BP_SKILLS_PATH": os.getenv("BP_SKILLS_PATH", ".agents/skills"),
        "BP_SANDBOX_RUNTIME": os.getenv("BP_SANDBOX_RUNTIME", "runsc"),
    }
    api_key_vars = [
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "OPENROUTER_API_KEY",
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
    ]
    for k in api_key_vars:
        val = os.getenv(k)
        if val:
            env_vars[k] = val
    lines = []
    if os.path.exists(env_path):
        existing = {}
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, _ = line.split("=", 1)
                    existing[k.strip()] = line
        for k, v in env_vars.items():
            if k in existing:
                key, _ = existing[k].split("=", 1)
                lines.append(f"{key}={v}\n")
            else:
                lines.append(f"{k}={v}\n")
        for line in open(env_path):
            ls = line.strip()
            if ls and not ls.startswith("#") and "=" in ls:
                k = ls.split("=", 1)[0].strip()
                if k not in env_vars:
                    lines.append(line if line.endswith("\n") else line + "\n")
            elif ls.startswith("#") or not ls:
                lines.append(line if line.endswith("\n") else line + "\n")
    else:
        for k, v in env_vars.items():
            lines.append(f"{k}={v}\n")
    content = "".join(lines)
    with open(env_path, "w") as f:
        f.write(content)
    logger.info("Wrote .env with REDMINE_API_KEY, REDMINE_PROJECT, and sandbox config")


def main() -> None:
    _wait_for_redmine()

    api_key = _get_admin_api_key()
    if not api_key:
        logger.info("Direct API auth failed, trying Rails runner fallback...")
        api_key = _prepare_admin_via_rails()
    else:
        logger.info(
            "API key obtained directly, ensuring settings and statuses via Rails runner..."
        )
        _enable_api_and_create_statuses()
    if not api_key:
        logger.error("Failed to obtain API key")
        sys.exit(1)
    logger.info("Admin API key: %s...", api_key[:8])

    project_id = _ensure_project_exists(api_key)
    logger.info("Using project id=%s", project_id)

    status_map = _ensure_issue_statuses(api_key)
    if not status_map:
        logger.error("No issue statuses configured")
        sys.exit(1)

    _write_env(api_key)
    logger.info("Bootstrap complete")


if __name__ == "__main__":
    main()
