from apolo_app_types_fixtures.constants import APP_ID
from apolo_apps_bifrost.outputs_processor import BifrostAppOutputProcessor

from ..conftest import NAMESPACE
from .test_inputs import generate


INTERNAL_HOST = f"bifrost-{APP_ID}.{NAMESPACE}"
EXTERNAL_HOST = f"bifrost--{APP_ID}.apps.some.org.neu.ro"


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
