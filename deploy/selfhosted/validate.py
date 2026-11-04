"""Read-only Compose checks using generated disposable secret files; no daemon/startup needed."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
with tempfile.TemporaryDirectory(prefix="hnw-compose-check-") as directory:
    directory = Path(directory)
    for name in ("owner", "runtime"):
        (directory / name).write_text(secrets.token_hex(32))
    settings = dict(HNW_PROJECT_NAME="hnw-validation", HNW_RELEASE="validation-only",
        HNW_PUBLIC_ORIGIN="https://news.example.invalid", HNW_DB_NAME="hype_world_news",
        HNW_DB_OWNER="hwn_owner", HNW_DB_RUNTIME="hwn_runtime",
        HNW_DB_OWNER_PASSWORD_FILE=str(directory / "owner"), HNW_DB_RUNTIME_PASSWORD_FILE=str(directory / "runtime"),
        HNW_WEB_BIND_PORT="18080", HNW_API_BIND_PORT="18000")
    env_file = directory / "settings"
    env_file.write_text("\n".join(f"{key}={value}" for key, value in settings.items()))
    # Ignore ambient HNW/Compose overrides; never read the developer's root .env.
    environment = {k: v for k, v in os.environ.items() if not k.startswith(("HNW_", "COMPOSE_"))}
    command = ["docker", "compose", "--project-name", "hnw-validation", "--env-file", str(env_file),
               "-f", str(root / "docker-compose.selfhosted.yml")]
    def config(extra=()):
        return json.loads(subprocess.check_output(command + list(extra) + ["--profile", "tools", "config", "--format", "json"],
                                                 env=environment, text=True))
    base = config()
    assert set(base["services"]) == {"news-db", "news-api", "news-web", "news-migrate", "news-provision"}
    for name, service in base["services"].items():
        assert not service.get("ports") and "container_name" not in service
        assert service["logging"]["options"] == {"max-size": "10m", "max-file": "3"}
        assert int(service["mem_limit"]) > 0 and float(service["cpus"]) > 0 and int(service["pids_limit"]) > 0
        if name in {"news-api", "news-db", "news-web"}:
            assert service["restart"] == "unless-stopped"
    assert base["networks"]["database"]["internal"]
    assert base["networks"]["database"]["name"] == "hnw-validation_database"
    assert base["volumes"]["news-data"]["name"] == "hnw-validation_news-data"
    assert base["services"]["news-db"]["networks"] == {"database": None}
    api = base["services"]["news-api"]
    assert api["environment"]["NEWS_STORAGE_BACKEND"] == "postgres"
    assert api["environment"]["AI_PROCESSING_PROVIDER"] == "disabled"
    assert api["environment"]["BACKEND_CORS_ORIGIN_REGEX"] == ""
    assert {s["source"] for s in api["secrets"]} == {"db_runtime_password"}
    assert api["read_only"] and api["cap_drop"] == ["ALL"]
    assert base["services"]["news-web"]["build"]["args"]["VITE_API_URL"] == settings["HNW_PUBLIC_ORIGIN"]
    for s in base["services"].values():
        assert "POSTGRES_PASSWORD" not in s.get("environment", {})
    overlay = config(["-f", str(root / "docker-compose.selfhosted.host-proxy.yml")])
    assert not overlay["services"]["news-db"].get("ports")
    for name in ("news-api", "news-web"):
        assert len(overlay["services"][name]["ports"]) == 1
        assert overlay["services"][name]["ports"][0]["host_ip"] == "127.0.0.1"
    print("PASS: standalone Compose, namespaced networks/volume, no default host ports, loopback overlay, file secrets, resource limits and log rotation.")
