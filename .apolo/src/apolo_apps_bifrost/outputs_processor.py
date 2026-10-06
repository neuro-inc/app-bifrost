import typing as t

from apolo_app_types.clients.kube import get_current_namespace
from apolo_app_types.outputs.base import BaseAppOutputsProcessor
from apolo_app_types.protocols.common import (
    ApoloSecret,
    HuggingFaceModel,
    OpenAICompatChatAPI,
    RestAPI,
    ServiceAPI,
)
from apolo_app_types.protocols.common.networking import WebApp
from apolo_apps_bifrost.app_types import BifrostAppOutputs
from apolo_apps_bifrost.inputs_processor import ADMIN_PASSWORD_ENV, VLLM_PROVIDER


BIFROST_PORT = 8080
INGRESS_PORT = 443
API_BASE_PATH = "/v1"


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

        chat_apis = []
        for model in _get_vllm_models(chart_values):
            hf_model = HuggingFaceModel(model_hf_name=f"{VLLM_PROVIDER}/{model}")
            chat_apis.append(
                ServiceAPI[OpenAICompatChatAPI](
                    internal_url=OpenAICompatChatAPI(**internal, hf_model=hf_model),
                    external_url=OpenAICompatChatAPI(**external, hf_model=hf_model)
                    if external
                    else None,
                )
            )

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
            chat_apis=chat_apis,
            admin_username=auth_config.get("adminUsername"),
            admin_password=_get_admin_password(chart_values),
        )
