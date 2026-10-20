import json
from pathlib import Path

from apolo_app_types_fixtures.constants import APP_ID
from apolo_apps_bifrost.app_types import BifrostAppInputs
from apolo_apps_bifrost.outputs_processor import BifrostAppOutputProcessor

from apolo_app_types.protocols.common import OpenAICompatAPI, OpenAICompatCapability
from apolo_app_types.protocols.common.openai_compat import get_api_base_url

from ..conftest import NAMESPACE
from .test_inputs import generate


INTERNAL_HOST = f"bifrost-{APP_ID}.{NAMESPACE}"
EXTERNAL_HOST = f"bifrost--{APP_ID}.apps.some.org.neu.ro"
DATA = Path(__file__).parent / "data"


def load(name):
    return json.loads((DATA / name).read_text())


def model_names(apis):
    return [api["internal_url"]["hf_model"]["model_hf_name"] for api in apis]


VLLM_CHAT = ["chat", "completions", "responses"]
V26_10_1_OPENAI_MODELS = [
    {
        "name": "vllm/meta-llama/Llama-3.1-8B-Instruct",
        "capabilities": VLLM_CHAT,
        "__type__": "OpenAICompatModel",
    },
    {"name": "vllm/qwen", "capabilities": VLLM_CHAT, "__type__": "OpenAICompatModel"},
]


def openai_models(api):
    return [
        (model["name"], model["capabilities"])
        for model in api["internal_url"]["models"]
    ]


async def test_outputs_from_generated_values(setup_clients, full_inputs):
    values = await generate(setup_clients, full_inputs)

    outputs = await BifrostAppOutputProcessor().generate_outputs(
        helm_values=values, app_instance_id="bifrost-app"
    )

    assert outputs["app_url"]["internal_url"] == {
        "host": INTERNAL_HOST,
        "port": 8080,
        "protocol": "http",
        "timeout": 30.0,
        "base_path": "/",
        "api_type": "webapp",
        "__type__": "WebApp",
    }
    assert outputs["app_url"]["external_url"]["host"] == EXTERNAL_HOST
    assert outputs["app_url"]["external_url"]["protocol"] == "https"
    assert outputs["app_url"]["external_url"]["port"] == 443
    assert outputs["gateway_api"]["internal_url"]["base_path"] == "/v1"
    assert outputs["gateway_api"]["external_url"]["host"] == EXTERNAL_HOST
    assert outputs["admin_username"] == "admin"
    assert outputs["admin_password"]["key"] == "bifrost-admin-password"


async def test_one_chat_api_per_model(setup_clients, full_inputs):
    values = await generate(setup_clients, full_inputs)

    outputs = await BifrostAppOutputProcessor().generate_outputs(
        helm_values=values, app_instance_id="bifrost-app"
    )

    assert [
        api["internal_url"]["hf_model"]["model_hf_name"] for api in outputs["chat_apis"]
    ] == ["vllm/meta-llama/Llama-3.1-8B-Instruct", "vllm/qwen"]
    for api in outputs["chat_apis"]:
        assert api["internal_url"]["host"] == INTERNAL_HOST
        assert api["internal_url"]["port"] == 8080
        assert api["internal_url"]["api_base_path"] == "/v1"
        assert api["external_url"]["host"] == EXTERNAL_HOST
        assert api["external_url"]["port"] == 443
        assert api["external_url"]["protocol"] == "https"


async def test_outputs_without_backends(setup_clients, minimal_inputs):
    values = await generate(setup_clients, minimal_inputs)

    outputs = await BifrostAppOutputProcessor().generate_outputs(
        helm_values=values, app_instance_id="bifrost-app"
    )

    assert outputs["chat_apis"] == []
    assert outputs["embeddings_apis"] == []
    assert outputs["gateway_api"]["internal_url"]["host"] == INTERNAL_HOST


async def test_model_named_like_a_provider_keeps_the_vllm_prefix(
    setup_clients, minimal_inputs, full_inputs
):
    backend = full_inputs.vllm_backends[2].model_copy(
        update={"served_model_name": "openai/gpt-oss-20b"}
    )
    inputs = minimal_inputs.model_copy(update={"vllm_backends": [backend]})
    values = await generate(setup_clients, inputs)

    outputs = await BifrostAppOutputProcessor().generate_outputs(
        helm_values=values, app_instance_id="bifrost-app"
    )

    assert [
        api["internal_url"]["hf_model"]["model_hf_name"] for api in outputs["chat_apis"]
    ] == ["vllm/openai/gpt-oss-20b"]


async def test_embeddings_and_provider_models(setup_clients, models_inputs):
    values = await generate(setup_clients, models_inputs)

    outputs = await BifrostAppOutputProcessor().generate_outputs(
        helm_values=values, app_instance_id="bifrost-app"
    )

    assert model_names(outputs["chat_apis"]) == [
        "vllm/meta-llama/Llama-3.1-8B-Instruct",
        "vllm/qwen",
        "openai/gpt-4o-mini",
        "openai/gpt-4.1",
        "anthropic/claude-haiku-4-5",
    ]
    assert model_names(outputs["embeddings_apis"]) == [
        "vllm/BAAI/bge-small-en-v1.5",
        "vllm/intfloat/multilingual-e5-small",
        "openai/text-embedding-3-small",
    ]
    for api in outputs["embeddings_apis"]:
        assert api["__type__"] == "ServiceAPI[OpenAICompatEmbeddingsAPI]"
        for url, host, port in (
            (api["internal_url"], INTERNAL_HOST, 8080),
            (api["external_url"], EXTERNAL_HOST, 443),
        ):
            assert url["__type__"] == "OpenAICompatEmbeddingsAPI"
            assert url["openai_api_type"] == "embeddings"
            assert (url["host"], url["port"]) == (host, port)
            assert (url["base_path"], url["api_base_path"]) == ("/", "/v1")


async def test_v26_10_1_inputs_keep_their_values_and_outputs(setup_clients):
    inputs = BifrostAppInputs.model_validate(load("v26.10.1-inputs.json"))
    expected_values = load("v26.10.1-values.json")
    expected_outputs = load("v26.10.1-outputs.json")

    values = await generate(setup_clients, inputs)
    outputs = await BifrostAppOutputProcessor().generate_outputs(
        helm_values=values, app_instance_id="bifrost-app"
    )

    assert values.pop("gateway_models") == {
        "chat": ["vllm/meta-llama/Llama-3.1-8B-Instruct", "vllm/qwen"],
        "embeddings": [],
    }
    assert values == expected_values
    assert outputs.pop("embeddings_apis") == []
    openai_api = outputs.pop("openai_api")
    assert openai_api["internal_url"]["models"] == V26_10_1_OPENAI_MODELS
    assert outputs == expected_outputs


async def test_outputs_from_v26_10_1_values():
    outputs = await BifrostAppOutputProcessor().generate_outputs(
        helm_values=load("v26.10.1-values.json"), app_instance_id="bifrost-app"
    )

    assert outputs.pop("embeddings_apis") == []
    openai_api = outputs.pop("openai_api")
    assert openai_api["internal_url"]["models"] == V26_10_1_OPENAI_MODELS
    assert openai_api["external_url"]["models"] == V26_10_1_OPENAI_MODELS
    assert outputs == load("v26.10.1-outputs.json")


async def test_openai_api_lists_every_model_with_its_capabilities(
    setup_clients, models_inputs
):
    values = await generate(setup_clients, models_inputs)

    outputs = await BifrostAppOutputProcessor().generate_outputs(
        helm_values=values, app_instance_id="bifrost-app"
    )

    api = outputs["openai_api"]
    assert api["__type__"] == "ServiceAPI[OpenAICompatAPI]"
    assert openai_models(api) == [
        ("vllm/meta-llama/Llama-3.1-8B-Instruct", VLLM_CHAT),
        ("vllm/qwen", VLLM_CHAT),
        ("openai/gpt-4o-mini", ["chat"]),
        ("openai/gpt-4.1", ["chat"]),
        ("anthropic/claude-haiku-4-5", ["chat"]),
        ("vllm/BAAI/bge-small-en-v1.5", ["embeddings"]),
        ("vllm/intfloat/multilingual-e5-small", ["embeddings"]),
        ("openai/text-embedding-3-small", ["embeddings"]),
    ]
    for url, host, port, protocol in (
        (api["internal_url"], INTERNAL_HOST, 8080, "http"),
        (api["external_url"], EXTERNAL_HOST, 443, "https"),
    ):
        assert url["__type__"] == "OpenAICompatAPI"
        assert (url["host"], url["port"], url["protocol"]) == (host, port, protocol)
        assert (url["base_path"], url["api_base_path"]) == ("/", "/v1")
        assert url["models"] == api["internal_url"]["models"]


async def test_openai_api_without_models(setup_clients, minimal_inputs):
    values = await generate(setup_clients, minimal_inputs)

    outputs = await BifrostAppOutputProcessor().generate_outputs(
        helm_values=values, app_instance_id="bifrost-app"
    )

    assert outputs["openai_api"]["internal_url"]["host"] == INTERNAL_HOST
    assert outputs["openai_api"]["internal_url"]["models"] == []


async def test_openai_api_validates_as_the_integration_type(
    setup_clients, models_inputs
):
    values = await generate(setup_clients, models_inputs)
    outputs = await BifrostAppOutputProcessor().generate_outputs(
        helm_values=values, app_instance_id="bifrost-app"
    )

    api = OpenAICompatAPI.model_validate(outputs["openai_api"]["internal_url"])

    assert api.get_model_names(OpenAICompatCapability.EMBEDDINGS) == [
        "vllm/BAAI/bge-small-en-v1.5",
        "vllm/intfloat/multilingual-e5-small",
        "openai/text-embedding-3-small",
    ]
    assert get_api_base_url(api) == f"http://{INTERNAL_HOST}:8080/v1"
