import pytest
from apolo_app_types_fixtures.constants import (
    APP_ID,
    APP_SECRETS_NAME,
    DEFAULT_NAMESPACE,
)
from apolo_apps_bifrost.app_types import (
    BifrostAppInputs,
    EmbeddingsBackend,
    ExternalProvider,
    PostgresStorage,
    ProviderNames,
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
    OpenAICompatEmbeddingsAPI,
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


async def test_embedding_backends(setup_clients, models_inputs):
    values = await generate(setup_clients, models_inputs)

    gateway = values["bifrost"]["bifrost"]
    keys = gateway["providers"]["vllm"]["keys"]
    assert [key["name"] for key in keys[:3]] == [
        "vllm-meta-llama-llama-3-1-8b-instruct-99423d51fb0b",
        "vllm-meta-llama-llama-3-1-8b-instruct-056d09bfba79",
        "vllm-qwen-f6f119267977",
    ]
    assert keys[3:] == [
        {
            "name": "vllm-baai-bge-small-en-v1-5-23299d9c6962",
            "value": "",
            "models": ["BAAI/bge-small-en-v1.5"],
            "weight": 1,
            "vllm_key_config": {
                "url": "http://tei.namespace:80",
                "model_name": "BAAI/bge-small-en-v1.5",
            },
        },
        {
            "name": "vllm-intfloat-multilingual-e5-small-908d3a0613a4",
            "value": "env.BIFROST_PROVIDER_KEY_4",
            "models": ["intfloat/multilingual-e5-small"],
            "weight": 1,
            "vllm_key_config": {
                "url": "http://vllm-embed.namespace:8000",
                "model_name": "intfloat/multilingual-e5-small",
            },
        },
    ]
    assert [secret["key"] for secret in gateway["providerSecrets"].values()] == [
        "openai-key",
        "openai-key-2",
        "anthropic-key",
        "llama-api-key",
        "e5-api-key",
    ]
    assert gateway["providers"]["openai"]["keys"][0]["models"] == ["*"]


async def test_gateway_models(setup_clients, models_inputs):
    values = await generate(setup_clients, models_inputs)

    assert values["gateway_models"] == {
        "chat": [
            "vllm/meta-llama/Llama-3.1-8B-Instruct",
            "vllm/qwen",
            "openai/gpt-4o-mini",
            "openai/gpt-4.1",
            "anthropic/claude-haiku-4-5",
        ],
        "embeddings": [
            "vllm/BAAI/bge-small-en-v1.5",
            "vllm/intfloat/multilingual-e5-small",
            "openai/text-embedding-3-small",
        ],
    }


async def test_gateway_models_without_backends(setup_clients, minimal_inputs):
    values = await generate(setup_clients, minimal_inputs)

    assert values["gateway_models"] == {"chat": [], "embeddings": []}


async def test_embeddings_only(setup_clients, minimal_inputs, embedding_backends):
    inputs = BifrostAppInputs.model_validate(
        {
            **minimal_inputs.model_dump(),
            "embedding_backends": [item.model_dump() for item in embedding_backends],
        }
    )

    values = await generate(setup_clients, inputs)

    providers = values["bifrost"]["bifrost"]["providers"]
    assert list(providers) == ["vllm"]
    assert [key["models"] for key in providers["vllm"]["keys"]] == [
        ["BAAI/bge-small-en-v1.5"],
        ["intfloat/multilingual-e5-small"],
    ]
    assert values["gateway_models"]["chat"] == []


async def test_key_names_with_embeddings_do_not_depend_on_the_order(
    setup_clients, models_inputs
):
    data = models_inputs.model_dump()
    reordered = BifrostAppInputs.model_validate(
        {
            **data,
            "vllm_backends": data["vllm_backends"][::-1],
            "embedding_backends": data["embedding_backends"][::-1],
            "providers": data["providers"][::-1],
        }
    )

    owners = key_owners(await generate(setup_clients, models_inputs))
    assert len(owners) == 8
    assert owners == key_owners(await generate(setup_clients, reordered))


@pytest.mark.parametrize(
    "provider",
    [
        ProviderNames.ANTHROPIC,
        ProviderNames.GROQ,
        ProviderNames.PERPLEXITY,
        ProviderNames.CEREBRAS,
        ProviderNames.XAI,
    ],
)
def test_embedding_models_of_a_provider_without_embeddings_are_rejected(provider):
    with pytest.raises(ValidationError, match=f"serves no embeddings from {provider}"):
        ExternalProvider(
            provider=provider,
            api_key=ApoloSecret(key="key"),
            embedding_models=["some-model"],
        )

    provider_input = ExternalProvider(
        provider=provider, api_key=ApoloSecret(key="key"), chat_models=["some-model"]
    )
    assert provider_input.chat_models == ["some-model"]


@pytest.mark.parametrize(
    "provider",
    [
        ProviderNames.OPENAI,
        ProviderNames.GEMINI,
        ProviderNames.MISTRAL,
        ProviderNames.COHERE,
        ProviderNames.OPENROUTER,
        ProviderNames.HUGGINGFACE,
        ProviderNames.NEBIUS,
    ],
)
def test_embedding_models_of_a_provider_with_embeddings(provider):
    provider_input = ExternalProvider(
        provider=provider,
        api_key=ApoloSecret(key="key"),
        embedding_models=["some-model"],
    )

    assert provider_input.embedding_models == ["some-model"]


def test_provider_model_names_are_stripped_and_not_blank():
    provider = ExternalProvider(
        provider=ProviderNames.OPENAI,
        api_key=ApoloSecret(key="key"),
        chat_models=[" gpt-4o-mini "],
    )
    assert provider.chat_models == ["gpt-4o-mini"]

    with pytest.raises(ValidationError, match="must not be blank"):
        ExternalProvider(
            provider=ProviderNames.OPENAI,
            api_key=ApoloSecret(key="key"),
            embedding_models=["  "],
        )


def test_one_model_for_chat_and_embeddings_is_rejected(models_inputs):
    data = models_inputs.model_dump()
    chat_backend = data["vllm_backends"][2]
    embeddings_backend = {
        **data["embedding_backends"][0],
        "served_model_name": chat_backend["served_model_name"],
    }

    with pytest.raises(ValidationError, match="vllm/qwen is listed both"):
        BifrostAppInputs.model_validate(
            {**data, "embedding_backends": [embeddings_backend]}
        )

    openai, openai_second, anthropic = data["providers"]
    with pytest.raises(ValidationError, match="openai/gpt-4o-mini is listed both"):
        BifrostAppInputs.model_validate(
            {
                **data,
                "providers": [
                    openai,
                    {**openai_second, "embedding_models": ["gpt-4o-mini"]},
                    anthropic,
                ],
            }
        )


def test_repeated_embedding_backends_are_rejected(models_inputs):
    data = models_inputs.model_dump()

    with pytest.raises(
        ValidationError, match="embeddings backend is listed more than once"
    ):
        BifrostAppInputs.model_validate(
            {**data, "embedding_backends": data["embedding_backends"][:1] * 2}
        )


def test_embeddings_backend_needs_a_model_name():
    api = OpenAICompatEmbeddingsAPI(host="tei.namespace", port=80, protocol="http")

    with pytest.raises(ValidationError, match="served model name"):
        EmbeddingsBackend(api=api)

    assert EmbeddingsBackend(api=api, served_model_name="bge").model_name == "bge"


def test_backends_take_only_their_own_api_type(models_inputs):
    chat_api = models_inputs.vllm_backends[0].api.model_dump()
    embeddings_api = models_inputs.embedding_backends[0].api.model_dump()

    with pytest.raises(ValidationError):
        VLLMBackend.model_validate({"api": embeddings_api})
    with pytest.raises(ValidationError):
        EmbeddingsBackend.model_validate({"api": chat_api})


@pytest.mark.parametrize(
    ("backend_type", "api_type"),
    [
        (VLLMBackend, OpenAICompatChatAPI),
        (EmbeddingsBackend, OpenAICompatEmbeddingsAPI),
    ],
)
@pytest.mark.parametrize(
    ("base_path", "url"),
    [
        ("/", "http://vllm.namespace:8000"),
        ("", "http://vllm.namespace:8000"),
        ("/proxy/llama/", "http://vllm.namespace:8000/proxy/llama"),
        ("proxy", "http://vllm.namespace:8000/proxy"),
    ],
)
def test_backend_url_keeps_the_base_path(backend_type, api_type, base_path, url):
    api = api_type(
        host="vllm.namespace", port=8000, protocol="http", base_path=base_path
    )

    assert backend_type(api=api, served_model_name="model").url == url


async def test_prefixed_backend_key(setup_clients, minimal_inputs, full_inputs):
    backend = full_inputs.vllm_backends[2].model_dump()
    prefixed = {**backend, "api": {**backend["api"], "base_path": "/qwen/"}}
    inputs = BifrostAppInputs.model_validate(
        {**minimal_inputs.model_dump(), "vllm_backends": [backend, prefixed]}
    )

    values = await generate(setup_clients, inputs)

    keys = values["bifrost"]["bifrost"]["providers"]["vllm"]["keys"]
    assert [(key["name"], key["vllm_key_config"]["url"]) for key in keys] == [
        ("vllm-qwen-f6f119267977", "http://qwen.namespace:8000"),
        ("vllm-qwen-b8574d8cbd42", "http://qwen.namespace:8000/qwen"),
    ]


@pytest.mark.parametrize(
    ("provider", "field", "name"),
    [
        (ProviderNames.OPENAI, "chat_models", "openai/gpt-4o-mini"),
        (ProviderNames.OPENAI, "embedding_models", "openai/text-embedding-3-small"),
        (ProviderNames.ANTHROPIC, "chat_models", "anthropic/claude-haiku-4-5"),
        (ProviderNames.GEMINI, "chat_models", "gemini/gemini-2.5-flash"),
    ],
)
def test_provider_model_with_its_own_prefix_is_rejected(provider, field, name):
    with pytest.raises(ValidationError, match="without the provider prefix"):
        ExternalProvider(
            provider=provider, api_key=ApoloSecret(key="key"), **{field: [name]}
        )


@pytest.mark.parametrize(
    ("provider", "name"),
    [
        (ProviderNames.OPENAI, "ft:gpt-4o-mini:org/custom"),
        (ProviderNames.GROQ, "meta-llama/llama-4-scout-17b-16e-instruct"),
        (ProviderNames.OPENROUTER, "anthropic/claude-sonnet-4"),
        (ProviderNames.OPENROUTER, "openrouter/auto"),
        (ProviderNames.HUGGINGFACE, "huggingface/CodeBERTa-small-v1"),
    ],
)
def test_provider_model_names_keep_their_slashes(provider, name):
    provider_input = ExternalProvider(
        provider=provider, api_key=ApoloSecret(key="key"), chat_models=[name]
    )

    assert provider_input.chat_models == [name]
