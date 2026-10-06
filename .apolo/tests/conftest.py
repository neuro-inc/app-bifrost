from decimal import Decimal

import pytest
from apolo_apps_bifrost.app_types import (
    BifrostAppInputs,
    BifrostSecurity,
    ExternalProvider,
    PostgresStorage,
    ProviderNames,
    VLLMBackend,
)
from apolo_sdk import Preset

from apolo_app_types.protocols.common import (
    ApoloSecret,
    HuggingFaceModel,
    OpenAICompatChatAPI,
    Preset as PresetInput,
)
from apolo_app_types.protocols.postgres import CrunchyPostgresUserCredentials


pytest_plugins = [
    "apolo_app_types_fixtures.apolo_clients",
]

MEBIBYTE = 1 << 20
PRESETS = {
    "gateway-small": Preset(
        cpu=1.0,
        memory=512 * MEBIBYTE,
        credits_per_hour=Decimal("0.1"),
        available_resource_pool_names=("cpu_pool",),
    ),
    "gateway-tiny": Preset(
        cpu=0.1,
        memory=100 * MEBIBYTE,
        credits_per_hour=Decimal("0.01"),
        available_resource_pool_names=("cpu_pool",),
    ),
    "gateway-large": Preset(
        cpu=4.0,
        memory=8192 * MEBIBYTE,
        credits_per_hour=Decimal("0.4"),
        available_resource_pool_names=("cpu_pool",),
    ),
}
NAMESPACE = "platform--org--project--0a1b2c3d"


@pytest.fixture
def presets_available():
    return PRESETS


@pytest.fixture
def security():
    return BifrostSecurity(
        admin_password=ApoloSecret(key="bifrost-admin-password"),
        encryption_key=ApoloSecret(key="bifrost-encryption-key"),
    )


@pytest.fixture
def minimal_inputs(security):
    return BifrostAppInputs(preset=PresetInput(name="gateway-small"), security=security)


@pytest.fixture
def full_inputs(security):
    return BifrostAppInputs(
        preset=PresetInput(name="gateway-large"),
        security=security.model_copy(update={"require_virtual_key": True}),
        storage=PostgresStorage(
            credentials=CrunchyPostgresUserCredentials(
                user="bifrost",
                password=ApoloSecret(key="pg-bifrost-password"),
                host="pg-app-primary.namespace.svc",
                port=5432,
                pgbouncer_host="pg-app-pgbouncer.namespace.svc",
                pgbouncer_port=5432,
                dbname="bifrost",
            )
        ),
        vllm_backends=[
            VLLMBackend(
                api=OpenAICompatChatAPI(
                    host="llama.namespace",
                    port=8000,
                    protocol="http",
                    hf_model=HuggingFaceModel(
                        model_hf_name="meta-llama/Llama-3.1-8B-Instruct"
                    ),
                ),
                api_key=ApoloSecret(key="llama-api-key"),
            ),
            VLLMBackend(
                api=OpenAICompatChatAPI(
                    host="llama-second.namespace",
                    port=8000,
                    protocol="http",
                    hf_model=HuggingFaceModel(
                        model_hf_name="meta-llama/Llama-3.1-8B-Instruct"
                    ),
                ),
            ),
            VLLMBackend(
                api=OpenAICompatChatAPI(
                    host="qwen.namespace", port=8000, protocol="http"
                ),
                served_model_name="qwen",
            ),
        ],
        providers=[
            ExternalProvider(
                provider=ProviderNames.OPENAI, api_key=ApoloSecret(key="openai-key")
            ),
            ExternalProvider(
                provider=ProviderNames.OPENAI, api_key=ApoloSecret(key="openai-key-2")
            ),
            ExternalProvider(
                provider=ProviderNames.ANTHROPIC,
                api_key=ApoloSecret(key="anthropic-key"),
            ),
        ],
    )


@pytest.fixture(autouse=True)
def _namespace(monkeypatch):
    monkeypatch.setenv("APOLO_APP_NAMESPACE", NAMESPACE)
