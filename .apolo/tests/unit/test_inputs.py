import pytest
from apolo_app_types_fixtures.constants import (
    APP_ID,
    APP_SECRETS_NAME,
    DEFAULT_NAMESPACE,
)
from apolo_apps_bifrost.app_types import (
    BifrostAppInputs,
    PostgresStorage,
    SQLiteStorage,
    VLLMBackend,
)
from apolo_apps_bifrost.inputs_processor import (
    BifrostAppChartValueProcessor,
    _KeyNames,
)
from pydantic import ValidationError

from apolo_app_types.protocols.common import (
    ApoloSecret,
    BasicNetworkingConfig,
    IngressHttp,
    NoAuth,
    OpenAICompatChatAPI,
    Preset,
)
from apolo_app_types.protocols.postgres import CrunchyPostgresUserCredentials


PLACEHOLDER_PROVIDERS = {
    "vllm": {
        "keys": [
            {
                "name": "no-backends",
                "value": "",
                "models": [],
                "weight": 1,
                "enabled": False,
                "vllm_key_config": {
                    "url": "http://localhost:8000",
                    "model_name": "no-backends",
                },
            }
        ],
        "network_config": {"allow_private_network": True},
    }
}


async def generate(apolo_client, inputs):
    processor = BifrostAppChartValueProcessor(client=apolo_client)
    return await processor.gen_extra_values(
        input_=inputs,
        app_name="bifrost-app",
        namespace=DEFAULT_NAMESPACE,
        app_secrets_name=APP_SECRETS_NAME,
        app_id=APP_ID,
    )


async def test_minimal_values(setup_clients, minimal_inputs):
    values = await generate(setup_clients, minimal_inputs)

    assert values["apolo_app_id"] == APP_ID
    chart = values["bifrost"]
    assert chart["fullnameOverride"] == f"bifrost-{APP_ID}"
    assert chart["resources"]["limits"] == {"cpu": "1000.0m", "memory": "512M"}
    assert chart["podLabels"] == {
        "platform.apolo.us/component": "app",
        "platform.apolo.us/preset": "gateway-small",
    }
    assert chart["storage"] == {
        "mode": "sqlite",
        "persistence": {"enabled": True, "size": "10Gi"},
    }
    assert "postgresql" not in chart
    assert chart["env"] == [
        {
            "name": "BIFROST_ADMIN_PASSWORD",
            "valueFrom": {
                "secretKeyRef": {
                    "name": APP_SECRETS_NAME,
                    "key": "bifrost-admin-password",
                }
            },
        },
        {"name": "GOMEMLIMIT", "value": "439MiB"},
    ]
    assert chart["bifrost"] == {
        "encryptionKeySecret": {
            "name": APP_SECRETS_NAME,
            "key": "bifrost-encryption-key",
        },
        "authConfig": {"adminUsername": "admin"},
        "client": {"enforceAuthOnInference": False, "maxRequestBodySizeMb": 19},
        "providerSecrets": {},
        "providers": PLACEHOLDER_PROVIDERS,
    }


async def test_ingress_has_no_nested_ingress_maps(setup_clients, minimal_inputs):
    values = await generate(setup_clients, minimal_inputs)

    ingress = values["bifrost"]["ingress"]
    assert set(ingress) == {"enabled", "className", "annotations", "hosts"}
    assert ingress["enabled"] is True
    assert ingress["className"] == "traefik"
    assert ingress["hosts"][0]["host"] == f"bifrost--{APP_ID}.apps.some.org.neu.ro"
    assert ingress["annotations"] == {
        "traefik.ingress.kubernetes.io/router.middlewares": (
            "platform-platform-control-plane-ingress-auth@kubernetescrd"
        )
    }


async def test_memory_bounds_scale_with_the_preset(setup_clients, full_inputs):
    values = await generate(setup_clients, full_inputs)

    chart = values["bifrost"]
    assert chart["resources"]["limits"]["memory"] == "8192M"
    assert chart["env"][1] == {"name": "GOMEMLIMIT", "value": "7031MiB"}
    assert chart["bifrost"]["client"] == {
        "enforceAuthOnInference": True,
        "maxRequestBodySizeMb": 100,
    }


async def test_postgres_storage(setup_clients, full_inputs):
    values = await generate(setup_clients, full_inputs)

    chart = values["bifrost"]
    assert chart["storage"] == {"mode": "postgres"}
    assert chart["postgresql"] == {
        "external": {
            "enabled": True,
            "host": "pg-app-primary.namespace.svc",
            "port": 5432,
            "user": "bifrost",
            "database": "bifrost",
            "sslMode": "require",
            "existingSecret": APP_SECRETS_NAME,
            "passwordKey": "pg-bifrost-password",
        }
    }


async def test_vllm_backends(setup_clients, full_inputs):
    values = await generate(setup_clients, full_inputs)

    vllm = values["bifrost"]["bifrost"]["providers"]["vllm"]
    assert vllm["network_config"] == {"allow_private_network": True}
    assert vllm["keys"] == [
        {
            "name": "vllm-meta-llama-llama-3-1-8b-instruct-99423d51fb0b",
            "value": "env.BIFROST_PROVIDER_KEY_3",
            "models": ["meta-llama/Llama-3.1-8B-Instruct"],
            "weight": 1,
            "vllm_key_config": {
                "url": "http://llama.namespace:8000",
                "model_name": "meta-llama/Llama-3.1-8B-Instruct",
            },
        },
        {
            "name": "vllm-meta-llama-llama-3-1-8b-instruct-056d09bfba79",
            "value": "",
            "models": ["meta-llama/Llama-3.1-8B-Instruct"],
            "weight": 1,
            "vllm_key_config": {
                "url": "http://llama-second.namespace:8000",
                "model_name": "meta-llama/Llama-3.1-8B-Instruct",
            },
        },
        {
            "name": "vllm-qwen-f6f119267977",
            "value": "",
            "models": ["qwen"],
            "weight": 1,
            "vllm_key_config": {
                "url": "http://qwen.namespace:8000",
                "model_name": "qwen",
            },
        },
    ]


async def test_external_providers(setup_clients, full_inputs):
    values = await generate(setup_clients, full_inputs)

    gateway = values["bifrost"]["bifrost"]
    assert gateway["providers"]["openai"] == {
        "keys": [
            {
                "name": "openai-openai-key-865a1626c0ef",
                "value": "env.BIFROST_PROVIDER_KEY_0",
                "models": ["*"],
                "weight": 1,
            },
            {
                "name": "openai-openai-key-2-b759decfb60c",
                "value": "env.BIFROST_PROVIDER_KEY_1",
                "models": ["*"],
                "weight": 1,
            },
        ]
    }
    assert gateway["providers"]["anthropic"]["keys"][0]["value"] == (
        "env.BIFROST_PROVIDER_KEY_2"
    )
    assert gateway["providerSecrets"] == {
        "key-0": {
            "existingSecret": APP_SECRETS_NAME,
            "key": "openai-key",
            "envVar": "BIFROST_PROVIDER_KEY_0",
        },
        "key-1": {
            "existingSecret": APP_SECRETS_NAME,
            "key": "openai-key-2",
            "envVar": "BIFROST_PROVIDER_KEY_1",
        },
        "key-2": {
            "existingSecret": APP_SECRETS_NAME,
            "key": "anthropic-key",
            "envVar": "BIFROST_PROVIDER_KEY_2",
        },
        "key-3": {
            "existingSecret": APP_SECRETS_NAME,
            "key": "llama-api-key",
            "envVar": "BIFROST_PROVIDER_KEY_3",
        },
    }


async def test_no_secret_value_in_generated_values(setup_clients, full_inputs):
    values = await generate(setup_clients, full_inputs)

    chart = values["bifrost"]
    assert "adminPassword" not in chart["bifrost"]["authConfig"]
    assert "password" not in chart["postgresql"]["external"]
    assert "encryptionKey" not in chart["bifrost"]


def test_ingress_without_auth_requires_virtual_keys(security):
    networking = BasicNetworkingConfig(ingress_http=IngressHttp(auth=NoAuth()))

    with pytest.raises(ValidationError, match="requires virtual keys"):
        BifrostAppInputs(
            preset=Preset(name="gateway-small"),
            security=security,
            networking=networking,
        )

    inputs = BifrostAppInputs(
        preset=Preset(name="gateway-small"),
        security=security.model_copy(update={"require_virtual_key": True}),
        networking=networking,
    )
    assert inputs.security.require_virtual_key is True


def test_vllm_backend_needs_a_model_name():
    api = OpenAICompatChatAPI(host="vllm.namespace", port=8000, protocol="http")

    with pytest.raises(ValidationError, match="served model name"):
        VLLMBackend(api=api)

    assert VLLMBackend(api=api, served_model_name="custom").model_name == "custom"


def test_postgres_storage_needs_a_database():
    with pytest.raises(ValidationError, match="database name"):
        PostgresStorage(
            credentials=CrunchyPostgresUserCredentials(
                user="bifrost",
                password=ApoloSecret(key="pg-bifrost-password"),
                host="pg-app-primary.namespace.svc",
                port=5432,
            )
        )


def test_storage_defaults_to_sqlite(minimal_inputs):
    assert isinstance(minimal_inputs.storage, SQLiteStorage)
    assert minimal_inputs.storage.size_gb == 10


async def test_external_providers_only_need_no_placeholder(setup_clients, full_inputs):
    inputs = full_inputs.model_copy(update={"vllm_backends": []})

    values = await generate(setup_clients, inputs)

    assert set(values["bifrost"]["bifrost"]["providers"]) == {"openai", "anthropic"}


async def test_preset_without_enough_memory_is_rejected(setup_clients, security):
    inputs = BifrostAppInputs(preset=Preset(name="gateway-tiny"), security=security)

    with pytest.raises(ValueError, match="needs at least 512 MB"):
        await generate(setup_clients, inputs)


def key_owners(values):
    gateway = values["bifrost"]["bifrost"]
    secrets = {
        f"env.{secret['envVar']}": secret["key"]
        for secret in gateway["providerSecrets"].values()
    }
    return {
        key["name"]: (
            provider,
            secrets.get(key["value"], ""),
            key.get("vllm_key_config", {}).get("url", ""),
        )
        for provider, config in gateway["providers"].items()
        for key in config["keys"]
    }


async def test_key_names_do_not_depend_on_the_order(setup_clients, full_inputs):
    reordered = full_inputs.model_copy(
        update={
            "vllm_backends": full_inputs.vllm_backends[::-1],
            "providers": full_inputs.providers[::-1],
        }
    )

    owners = key_owners(await generate(setup_clients, full_inputs))
    assert len(owners) == 6
    assert owners == key_owners(await generate(setup_clients, reordered))


async def test_key_names_are_unique_across_providers(setup_clients, full_inputs):
    values = await generate(setup_clients, full_inputs)

    names = [
        key["name"]
        for config in values["bifrost"]["bifrost"]["providers"].values()
        for key in config["keys"]
    ]
    assert len(set(names)) == len(names)


def test_repeated_entries_are_rejected(full_inputs):
    data = full_inputs.model_dump()

    with pytest.raises(ValidationError, match="vLLM backend is listed more than once"):
        BifrostAppInputs.model_validate(
            {**data, "vllm_backends": data["vllm_backends"][:1] * 2}
        )
    with pytest.raises(ValidationError, match="API key is listed more than once"):
        BifrostAppInputs.model_validate(
            {**data, "providers": data["providers"][:1] * 2}
        )


def test_vllm_backend_rejects_a_blank_model_name():
    api = OpenAICompatChatAPI(
        host="vllm.namespace",
        port=8000,
        protocol="http",
        hf_model={"model_hf_name": "  "},
    )

    with pytest.raises(ValidationError, match="served model name"):
        VLLMBackend(api=api)


def test_storage_rejects_fields_of_another_storage(security):
    credentials = {
        "user": "bifrost",
        "password": {"key": "pg-bifrost-password"},
        "host": "pg-app-primary.namespace.svc",
        "port": 5432,
    }

    with pytest.raises(ValidationError):
        BifrostAppInputs.model_validate(
            {
                "preset": {"name": "gateway-small"},
                "security": security.model_dump(),
                "storage": {"credentials": credentials},
            }
        )


def test_similar_entries_get_distinct_bounded_key_names():
    names = _KeyNames()

    generated = [
        names.add("vllm", "qwen", ("http://a.b:8000", "qwen", "")),
        names.add("vllm", "qwen", ("http://a-b:8000", "qwen", "")),
        names.add("vllm", "qwen", ("http://a-b:8000", "qwen", "key-one")),
        names.add("vllm", "模型", ("http://a-b:8000", "模型", "")),
        names.add("vllm", "x" * 400, ("http://a-b:8000", "x" * 400, "")),
        names.add("openai", "key.a", ("openai", "key.a")),
        names.add("openai", "key-a", ("openai", "key-a")),
    ]

    assert len(set(generated)) == len(generated)
    assert max(len(name) for name in generated) <= 93
    assert all(name.startswith(("vllm-", "openai-")) for name in generated)


def test_repeated_key_identity_is_rejected():
    names = _KeyNames()
    names.add("vllm", "qwen", ("http://a.b:8000", "qwen", ""))

    with pytest.raises(ValueError, match="configured more than once"):
        names.add("vllm", "qwen", ("http://a.b:8000", "qwen", ""))


def test_one_endpoint_with_two_api_keys_is_accepted(full_inputs):
    backend = full_inputs.vllm_backends[0]
    second = backend.model_copy(update={"api_key": ApoloSecret(key="llama-api-key-2")})

    inputs = full_inputs.model_copy(update={"vllm_backends": [backend, second]})

    assert len({item.identity for item in inputs.vllm_backends}) == 2
    BifrostAppInputs.model_validate(inputs.model_dump())
