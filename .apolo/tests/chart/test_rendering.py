import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from apolo_app_types_fixtures.constants import APP_ID

from ..unit.test_inputs import generate


CHART_DIR = Path(__file__).parents[3] / "charts" / "bifrost-app"
RELEASE = "apolo-project-bifrost-0a1b2c3d"

pytestmark = pytest.mark.skipif(
    not os.environ.get("CI")
    and (shutil.which("helm") is None or not any((CHART_DIR / "charts").glob("*.tgz"))),
    reason="needs helm and built chart dependencies (make test-helm)",
)


def render(values, tmp_path):
    values_file = tmp_path / "values.json"
    values_file.write_text(json.dumps(values))
    result = subprocess.run(  # noqa: S603
        [
            shutil.which("helm"),
            "template",
            RELEASE,
            str(CHART_DIR),
            "--namespace",
            "project",
            "--values",
            str(values_file),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    documents = [doc for doc in yaml.safe_load_all(result.stdout) if doc]
    return {(doc["kind"], doc["metadata"]["name"]): doc for doc in documents}


def get_config(manifests):
    config_map = next(
        doc for (kind, _), doc in manifests.items() if kind == "ConfigMap"
    )
    return json.loads(config_map["data"]["config.json"])


def get_container(workload):
    return workload["spec"]["template"]["spec"]["containers"][0]


async def test_sqlite_release(setup_clients, minimal_inputs, tmp_path):
    values = await generate(setup_clients, minimal_inputs)
    manifests = render(values, tmp_path)
    name = f"bifrost-{APP_ID}"

    assert {kind for kind, _ in manifests} == {
        "ConfigMap",
        "Ingress",
        "Service",
        "ServiceAccount",
        "StatefulSet",
    }
    ingress = manifests[("Ingress", name)]
    assert ingress["spec"]["ingressClassName"] == "traefik"
    assert ingress["spec"]["rules"][0]["host"] == (
        f"bifrost--{APP_ID}.apps.some.org.neu.ro"
    )
    assert ingress["spec"]["rules"][0]["http"]["paths"][0]["backend"] == {
        "service": {"name": name, "port": {"number": 8080}}
    }

    workload = manifests[("StatefulSet", name)]
    assert workload["spec"]["volumeClaimTemplates"][0]["spec"]["resources"] == {
        "requests": {"storage": "10Gi"}
    }
    labels = workload["spec"]["template"]["metadata"]["labels"]
    assert labels["application"] == "bifrost"
    assert labels["platform.apolo.us/preset"] == "gateway-small"
    container = get_container(workload)
    assert container["image"] == "docker.io/maximhq/bifrost:v2.2.6"
    assert container["resources"]["limits"]["memory"] == "512M"
    env = {item["name"]: item for item in container["env"]}
    assert env["GOMEMLIMIT"]["value"] == "439MiB"
    assert env["BIFROST_ADMIN_PASSWORD"]["valueFrom"]["secretKeyRef"] == {
        "name": "apps-secrets",
        "key": "bifrost-admin-password",
    }
    assert env["BIFROST_ENCRYPTION_KEY"]["valueFrom"]["secretKeyRef"] == {
        "name": "apps-secrets",
        "key": "bifrost-encryption-key",
    }

    config = get_config(manifests)
    assert config["source_of_truth"] == "config.json"
    assert config["auth_config"] == {
        "admin_username": "admin",
        "admin_password": "env.BIFROST_ADMIN_PASSWORD",
        "is_enabled": True,
    }
    assert config["client"]["enforce_auth_on_inference"] is False
    assert config["client"]["dual_credential_conflict_behavior"] == "prefer_vk"
    assert config["client"]["max_request_body_size_mb"] == 19
    assert config["config_store"]["type"] == "sqlite"
    assert list(config["providers"]) == ["vllm"]
    assert [
        (key["name"], key["enabled"], key["models"])
        for key in config["providers"]["vllm"]["keys"]
    ] == [("no-backends", False, [])]


async def test_postgres_release_with_backends(setup_clients, full_inputs, tmp_path):
    values = await generate(setup_clients, full_inputs)
    manifests = render(values, tmp_path)
    name = f"bifrost-{APP_ID}"

    assert {kind for kind, _ in manifests} == {
        "ConfigMap",
        "Deployment",
        "Ingress",
        "Service",
        "ServiceAccount",
    }
    env = {
        item["name"]: item
        for item in get_container(manifests[("Deployment", name)])["env"]
    }
    assert env["BIFROST_POSTGRES_PASSWORD"]["valueFrom"]["secretKeyRef"] == {
        "name": "apps-secrets",
        "key": "pg-bifrost-password",
    }
    assert env["BIFROST_PROVIDER_KEY_3"]["valueFrom"]["secretKeyRef"] == {
        "name": "apps-secrets",
        "key": "llama-api-key",
    }

    config = get_config(manifests)
    assert config["client"]["enforce_auth_on_inference"] is True
    assert config["config_store"] == {
        "enabled": True,
        "type": "postgres",
        "config": {
            "host": "pg-app-primary.namespace.svc",
            "port": "5432",
            "user": "bifrost",
            "password": "env.BIFROST_POSTGRES_PASSWORD",
            "db_name": "bifrost",
            "ssl_mode": "require",
        },
    }
    assert set(config["providers"]) == {"openai", "anthropic", "vllm"}
    assert config["providers"]["openai"]["keys"][0]["value"] == (
        "env.BIFROST_PROVIDER_KEY_0"
    )
    vllm = config["providers"]["vllm"]
    assert vllm["network_config"] == {"allow_private_network": True}
    assert [key["vllm_key_config"] for key in vllm["keys"]] == [
        {
            "url": "http://llama.namespace:8000",
            "model_name": "meta-llama/Llama-3.1-8B-Instruct",
        },
        {
            "url": "http://llama-second.namespace:8000",
            "model_name": "meta-llama/Llama-3.1-8B-Instruct",
        },
        {"url": "http://qwen.namespace:8000", "model_name": "qwen"},
    ]
    rendered = json.dumps(config)
    assert "apps-secrets" not in rendered
