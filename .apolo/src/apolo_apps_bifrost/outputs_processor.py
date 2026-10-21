import typing as t

from apolo_app_types.clients.kube import get_current_namespace
from apolo_app_types.outputs.base import BaseAppOutputsProcessor
from apolo_app_types.protocols.common import (
    ApoloSecret,
    HuggingFaceModel,
    OpenAICompatAPI,
    OpenAICompatCapability,
    OpenAICompatChatAPI,
    OpenAICompatEmbeddingsAPI,
    OpenAICompatModel,
    RestAPI,
    ServiceAPI,
)
from apolo_app_types.protocols.common.networking import WebApp
from apolo_apps_bifrost.app_types import VLLM_PROVIDER, BifrostAppOutputs
from apolo_apps_bifrost.inputs_processor import ADMIN_PASSWORD_ENV, GATEWAY_MODELS_KEY


BIFROST_PORT = 8080
INGRESS_PORT = 443
API_BASE_PATH = "/v1"
VLLM_CHAT_CAPABILITIES = [
    OpenAICompatCapability.CHAT,
    OpenAICompatCapability.COMPLETIONS,
    OpenAICompatCapability.RESPONSES,
]
PROVIDER_CHAT_CAPABILITIES = [OpenAICompatCapability.CHAT]
EMBEDDINGS_CAPABILITIES = [OpenAICompatCapability.EMBEDDINGS]


def _get_external_host(chart_values: dict[str, t.Any]) -> str | None:
    ingress = chart_values.get("ingress") or {}
    hosts = ingress.get("hosts") or []
    if not ingress.get("enabled") or not hosts:
        return None
    return t.cast(str, hosts[0]["host"])


def _get_admin_password(chart_values: dict[str, t.Any]) -> ApoloSecret | None:
    for env in chart_values.get("env") or []:
        if env.get("name") == ADMIN_PASSWORD_ENV:
            return ApoloSecret(key=env["valueFrom"]["secretKeyRef"]["key"])
    return None


def _get_vllm_models(chart_values: dict[str, t.Any]) -> list[str]:
    providers = (chart_values.get("bifrost") or {}).get("providers") or {}
    keys = (providers.get(VLLM_PROVIDER) or {}).get("keys") or []
    models: list[str] = []
    for key in keys:
        model = key["vllm_key_config"]["model_name"]
        if key.get("enabled", True) and model not in models:
            models.append(model)
    return models


def _get_gateway_models(
    helm_values: dict[str, t.Any], chart_values: dict[str, t.Any]
) -> dict[str, list[str]]:
    models = helm_values.get(GATEWAY_MODELS_KEY)
    if models is None:
        return {
            "chat": [
                f"{VLLM_PROVIDER}/{model}" for model in _get_vllm_models(chart_values)
            ],
            "embeddings": [],
        }
    return t.cast(dict[str, list[str]], models)


def _get_openai_models(models: dict[str, list[str]]) -> list[OpenAICompatModel]:
    vllm_prefix = f"{VLLM_PROVIDER}/"
    return [
        *(
            OpenAICompatModel(
                name=name,
                capabilities=VLLM_CHAT_CAPABILITIES
                if name.startswith(vllm_prefix)
                else PROVIDER_CHAT_CAPABILITIES,
            )
            for name in models.get("chat", [])
        ),
        *(
            OpenAICompatModel(name=name, capabilities=EMBEDDINGS_CAPABILITIES)
            for name in models.get("embeddings", [])
        ),
    ]


def _get_model_apis[ModelAPI: (OpenAICompatChatAPI, OpenAICompatEmbeddingsAPI)](
    service_type: type[ServiceAPI[ModelAPI]],
    models: list[str],
    internal: dict[str, t.Any],
    external: dict[str, t.Any] | None,
) -> list[ServiceAPI[ModelAPI]]:
    apis = []
    for model in models:
        hf_model = HuggingFaceModel(model_hf_name=model)
        apis.append(
            service_type.model_validate(
                {
                    "internal_url": {**internal, "hf_model": hf_model},
                    "external_url": {**external, "hf_model": hf_model}
                    if external
                    else None,
                }
            )
        )
    return apis


class BifrostAppOutputProcessor(BaseAppOutputsProcessor[BifrostAppOutputs]):
    async def _generate_outputs(
        self,
        helm_values: dict[str, t.Any],
        app_instance_id: str,
    ) -> BifrostAppOutputs:
        chart_values = helm_values["bifrost"]
        internal: dict[str, t.Any] = {
            "host": f"{chart_values['fullnameOverride']}.{get_current_namespace()}",
            "port": BIFROST_PORT,
            "protocol": "http",
        }
        external_host = _get_external_host(chart_values)
        external: dict[str, t.Any] | None = (
            {"host": external_host, "port": INGRESS_PORT, "protocol": "https"}
            if external_host
            else None
        )

        models = _get_gateway_models(helm_values, chart_values)
        openai_models = _get_openai_models(models)

        auth_config = (chart_values.get("bifrost") or {}).get("authConfig") or {}
        return BifrostAppOutputs(
            app_url=ServiceAPI[WebApp](
                internal_url=WebApp(**internal, base_path="/"),
                external_url=WebApp(**external, base_path="/") if external else None,
            ),
            gateway_api=ServiceAPI[RestAPI](
                internal_url=RestAPI(**internal, base_path=API_BASE_PATH),
                external_url=RestAPI(**external, base_path=API_BASE_PATH)
                if external
                else None,
            ),
            openai_api=ServiceAPI[OpenAICompatAPI](
                internal_url=OpenAICompatAPI(**internal, models=openai_models),
                external_url=OpenAICompatAPI(**external, models=openai_models)
                if external
                else None,
            ),
            chat_apis=_get_model_apis(
                ServiceAPI[OpenAICompatChatAPI],
                models.get("chat", []),
                internal,
                external,
            ),
            embeddings_apis=_get_model_apis(
                ServiceAPI[OpenAICompatEmbeddingsAPI],
                models.get("embeddings", []),
                internal,
                external,
            ),
            admin_username=auth_config.get("adminUsername"),
            admin_password=_get_admin_password(chart_values),
        )
