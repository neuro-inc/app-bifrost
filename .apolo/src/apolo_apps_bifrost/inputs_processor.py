import hashlib
import json
import re
import typing as t

from apolo_app_types.app_types import AppType
from apolo_app_types.helm.apps.base import BaseChartValueProcessor
from apolo_app_types.helm.apps.common import gen_extra_values
from apolo_app_types.protocols.common import ApoloSecret
from apolo_app_types.protocols.common.secrets_ import serialize_optional_secret
from apolo_apps_bifrost.app_types import (
    BifrostAppInputs,
    ExternalProvider,
    PostgresStorage,
    VLLMBackend,
)


FULLNAME_PREFIX = "bifrost"
ADMIN_PASSWORD_ENV = "BIFROST_ADMIN_PASSWORD"
PROVIDER_KEY_ENV_PREFIX = "BIFROST_PROVIDER_KEY"
GO_MEMORY_LIMIT_RATIO = 0.9
MEMORY_MIB_PER_BODY_MB = 25
MAX_REQUEST_BODY_MB = 100
MIN_MEMORY_MIB = 480
VLLM_PROVIDER = "vllm"
KEY_NAME_PREFIX_LENGTH = 80
KEY_NAME_DIGEST_LENGTH = 12
PLACEHOLDER_KEY_NAME = "no-backends"
INGRESS_KEYS = ("enabled", "className", "annotations", "hosts")
MEMORY_UNITS = {
    "Ki": 1 << 10,
    "Mi": 1 << 20,
    "Gi": 1 << 30,
    "Ti": 1 << 40,
    "k": 10**3,
    "M": 10**6,
    "G": 10**9,
    "T": 10**12,
}
MEBIBYTE = 1 << 20


def get_fullname(app_id: str) -> str:
    return f"{FULLNAME_PREFIX}-{app_id}"


def _parse_memory(value: str) -> int:
    match = re.fullmatch(r"(\d+(?:\.\d+)?)([A-Za-z]*)", value.strip())
    if not match or (match.group(2) and match.group(2) not in MEMORY_UNITS):
        msg = f"Unsupported memory quantity: {value}"
        raise ValueError(msg)
    return int(float(match.group(1)) * MEMORY_UNITS.get(match.group(2), 1))


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


class _ProviderSecrets:
    def __init__(self, app_secrets_name: str) -> None:
        self._app_secrets_name = app_secrets_name
        self.values: dict[str, dict[str, str]] = {}

    def add(self, secret: ApoloSecret) -> str:
        index = len(self.values)
        env_var = f"{PROVIDER_KEY_ENV_PREFIX}_{index}"
        self.values[f"key-{index}"] = {
            "existingSecret": self._app_secrets_name,
            "key": secret.key,
            "envVar": env_var,
        }
        return f"env.{env_var}"


class _KeyNames:
    def __init__(self) -> None:
        self._used: set[str] = set()

    def add(self, prefix: str, label: str, identity: tuple[str, ...]) -> str:
        digest = hashlib.sha256(json.dumps(identity).encode()).hexdigest()
        readable = f"{prefix}-{_slug(label)}"[:KEY_NAME_PREFIX_LENGTH].rstrip("-")
        name = f"{readable}-{digest[:KEY_NAME_DIGEST_LENGTH]}"
        if name in self._used:
            msg = f"Provider key {name} is configured more than once"
            raise ValueError(msg)
        self._used.add(name)
        return name


def _build_vllm_provider(
    backends: list[VLLMBackend], secrets: _ProviderSecrets, names: _KeyNames
) -> dict[str, t.Any]:
    keys = []
    for backend in backends:
        model = backend.model_name
        keys.append(
            {
                "name": names.add(VLLM_PROVIDER, model, backend.identity),
                "value": secrets.add(backend.api_key) if backend.api_key else "",
                "models": [model],
                "weight": 1,
                "vllm_key_config": {"url": backend.url, "model_name": model},
            }
        )
    return {"keys": keys, "network_config": {"allow_private_network": True}}


def _build_vllm_placeholder() -> dict[str, t.Any]:
    return {
        "keys": [
            {
                "name": PLACEHOLDER_KEY_NAME,
                "value": "",
                "models": [],
                "weight": 1,
                "enabled": False,
                "vllm_key_config": {
                    "url": "http://localhost:8000",
                    "model_name": PLACEHOLDER_KEY_NAME,
                },
            }
        ],
        "network_config": {"allow_private_network": True},
    }


def _build_external_providers(
    providers: list[ExternalProvider], secrets: _ProviderSecrets, names: _KeyNames
) -> dict[str, t.Any]:
    result: dict[str, t.Any] = {}
    for provider in providers:
        name = provider.provider.value
        result.setdefault(name, {"keys": []})["keys"].append(
            {
                "name": names.add(name, provider.api_key.key, provider.identity),
                "value": secrets.add(provider.api_key),
                "models": ["*"],
                "weight": 1,
            }
        )
    return result


def _build_storage(input_: BifrostAppInputs, app_secrets_name: str) -> dict[str, t.Any]:
    storage = input_.storage
    if isinstance(storage, PostgresStorage):
        credentials = storage.credentials
        return {
            "storage": {"mode": "postgres"},
            "postgresql": {
                "external": {
                    "enabled": True,
                    "host": credentials.host,
                    "port": credentials.port,
                    "user": credentials.user,
                    "database": credentials.dbname,
                    "sslMode": "require",
                    "existingSecret": app_secrets_name,
                    "passwordKey": credentials.password.key,
                }
            },
        }
    return {
        "storage": {
            "mode": "sqlite",
            "persistence": {"enabled": True, "size": f"{storage.size_gb}Gi"},
        }
    }


class BifrostAppChartValueProcessor(BaseChartValueProcessor[BifrostAppInputs]):
    async def gen_extra_values(
        self,
        input_: BifrostAppInputs,
        app_name: str,
        namespace: str,
        app_id: str,
        app_secrets_name: str,
        *args: t.Any,
        **kwargs: t.Any,
    ) -> dict[str, t.Any]:
        extra_values = await gen_extra_values(
            apolo_client=self.client,
            preset_type=input_.preset,
            app_id=app_id,
            app_type=AppType.Bifrost,
            namespace=namespace,
            ingress_http=input_.networking.ingress_http,
        )
        memory_limit = _parse_memory(extra_values["resources"]["limits"]["memory"])
        memory_limit_mib = memory_limit // MEBIBYTE
        if memory_limit_mib < MIN_MEMORY_MIB:
            msg = (
                f"Preset {input_.preset.name} has {memory_limit_mib} MiB of memory, "
                "Bifrost needs at least 512 MB"
            )
            raise ValueError(msg)

        secrets = _ProviderSecrets(app_secrets_name)
        names = _KeyNames()
        providers = _build_external_providers(input_.providers, secrets, names)
        if input_.vllm_backends:
            providers[VLLM_PROVIDER] = _build_vllm_provider(
                input_.vllm_backends, secrets, names
            )
        if not providers:
            providers[VLLM_PROVIDER] = _build_vllm_placeholder()

        security = input_.security
        return {
            "apolo_app_id": extra_values["apolo_app_id"],
            "bifrost": {
                "fullnameOverride": get_fullname(app_id),
                "resources": extra_values["resources"],
                "tolerations": extra_values["tolerations"],
                "affinity": extra_values["affinity"],
                "podLabels": extra_values["podLabels"],
                "ingress": {
                    key: extra_values["ingress"][key]
                    for key in INGRESS_KEYS
                    if key in extra_values["ingress"]
                },
                **_build_storage(input_, app_secrets_name),
                "env": [
                    {
                        "name": ADMIN_PASSWORD_ENV,
                        **t.cast(
                            dict[str, t.Any],
                            serialize_optional_secret(
                                security.admin_password, app_secrets_name
                            ),
                        ),
                    },
                    {
                        "name": "GOMEMLIMIT",
                        "value": (
                            f"{int(memory_limit * GO_MEMORY_LIMIT_RATIO) // MEBIBYTE}"
                            "MiB"
                        ),
                    },
                ],
                "bifrost": {
                    "encryptionKeySecret": {
                        "name": app_secrets_name,
                        "key": security.encryption_key.key,
                    },
                    "authConfig": {"adminUsername": security.admin_username},
                    "client": {
                        "enforceAuthOnInference": security.require_virtual_key,
                        "maxRequestBodySizeMb": max(
                            1,
                            min(
                                MAX_REQUEST_BODY_MB,
                                memory_limit_mib // MEMORY_MIB_PER_BODY_MB,
                            ),
                        ),
                    },
                    "providerSecrets": secrets.values,
                    "providers": providers,
                },
            },
        }
