import enum
import typing as t

from pydantic import ConfigDict, Field, model_validator

from apolo_app_types.protocols.common import (
    AbstractAppFieldType,
    ApoloSecret,
    AppInputs,
    AppOutputs,
    BasicNetworkingConfig,
    NoAuth,
    OpenAICompatChatAPI,
    Preset,
    RestAPI,
    SchemaExtraMetadata,
    SchemaMetaType,
    ServiceAPI,
)
from apolo_app_types.protocols.postgres import CrunchyPostgresUserCredentials


class StorageTypes(enum.StrEnum):
    SQLITE = "sqlite"
    POSTGRES = "postgres"


class SQLiteStorage(AbstractAppFieldType):
    model_config = ConfigDict(
        protected_namespaces=(),
        json_schema_extra=SchemaExtraMetadata(
            title="SQLite",
            description="Keep configuration and request logs in a SQLite database "
            "on a dedicated volume. The gateway runs as a single instance.",
            is_configurable=False,
        ).as_json_schema_extra(),
    )
    storage_type: t.Literal[StorageTypes.SQLITE] = Field(default=StorageTypes.SQLITE)
    size_gb: int = Field(
        default=10,
        ge=1,
        json_schema_extra=SchemaExtraMetadata(
            title="Volume Size, GB",
            description="Size of the volume that holds the SQLite database.",
        ).as_json_schema_extra(),
    )

    @model_validator(mode="before")
    @classmethod
    def _reject_postgres_fields(cls, data: t.Any) -> t.Any:
        if isinstance(data, dict) and "credentials" in data:
            msg = "SQLite storage takes no PostgreSQL credentials"
            raise ValueError(msg)
        return data


class PostgresStorage(AbstractAppFieldType):
    model_config = ConfigDict(
        protected_namespaces=(),
        json_schema_extra=SchemaExtraMetadata(
            title="PostgreSQL",
            description="Keep configuration and request logs in a PostgreSQL "
            "database. PostgreSQL 16 or newer is required.",
            is_configurable=False,
        ).as_json_schema_extra(),
    )
    storage_type: t.Literal[StorageTypes.POSTGRES] = Field(
        default=StorageTypes.POSTGRES
    )
    credentials: CrunchyPostgresUserCredentials = Field(
        ...,
        json_schema_extra=SchemaExtraMetadata(
            title="PostgreSQL Credentials",
            description="A PostgreSQL user with its own database.",
            meta_type=SchemaMetaType.INTEGRATION,
        ).as_json_schema_extra(),
    )

    @model_validator(mode="after")
    def _require_database(self) -> t.Self:
        if not self.credentials.dbname:
            msg = "PostgreSQL credentials must include a database name"
            raise ValueError(msg)
        return self


class VLLMBackend(AbstractAppFieldType):
    model_config = ConfigDict(
        protected_namespaces=(),
        json_schema_extra=SchemaExtraMetadata(
            title="vLLM Backend",
            description="A vLLM server the gateway routes requests to.",
        ).as_json_schema_extra(),
    )
    api: OpenAICompatChatAPI = Field(
        ...,
        json_schema_extra=SchemaExtraMetadata(
            title="vLLM API",
            description="Chat API of a vLLM application in this project.",
            meta_type=SchemaMetaType.INTEGRATION,
        ).as_json_schema_extra(),
    )
    api_key: ApoloSecret | None = Field(
        default=None,
        json_schema_extra=SchemaExtraMetadata(
            title="API Key",
            description="Set it when the vLLM server is started with an API key.",
        ).as_json_schema_extra(),
    )
    served_model_name: str | None = Field(
        default=None,
        json_schema_extra=SchemaExtraMetadata(
            title="Served Model Name",
            description="Set it when the vLLM server serves the model under a "
            "name other than the Hugging Face model name.",
            is_advanced_field=True,
        ).as_json_schema_extra(),
    )

    @property
    def model_name(self) -> str:
        name = self.served_model_name or (
            self.api.hf_model.model_hf_name if self.api.hf_model else ""
        )
        return name.strip()

    @property
    def url(self) -> str:
        return f"{self.api.protocol}://{self.api.host}:{self.api.port}"

    @property
    def identity(self) -> tuple[str, ...]:
        return (self.url, self.model_name, self.api_key.key if self.api_key else "")

    @model_validator(mode="after")
    def _require_model_name(self) -> t.Self:
        if not self.model_name:
            msg = (
                "vLLM backend needs either the Hugging Face model of the API "
                "or a served model name"
            )
            raise ValueError(msg)
        return self


class ProviderNames(enum.StrEnum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"
    MISTRAL = "mistral"
    GROQ = "groq"
    COHERE = "cohere"
    OPENROUTER = "openrouter"
    PERPLEXITY = "perplexity"
    CEREBRAS = "cerebras"
    XAI = "xai"
    HUGGINGFACE = "huggingface"
    NEBIUS = "nebius"


class ExternalProvider(AbstractAppFieldType):
    model_config = ConfigDict(
        protected_namespaces=(),
        json_schema_extra=SchemaExtraMetadata(
            title="External Provider",
            description="A hosted model provider the gateway routes requests to.",
        ).as_json_schema_extra(),
    )
    provider: ProviderNames = Field(
        ...,
        json_schema_extra=SchemaExtraMetadata(
            title="Provider",
            description="Provider to route requests to.",
        ).as_json_schema_extra(),
    )
    api_key: ApoloSecret = Field(
        ...,
        json_schema_extra=SchemaExtraMetadata(
            title="API Key",
            description="API key of the provider account.",
        ).as_json_schema_extra(),
    )

    @property
    def identity(self) -> tuple[str, ...]:
        return (self.provider.value, self.api_key.key)


class BifrostSecurity(AbstractAppFieldType):
    model_config = ConfigDict(
        protected_namespaces=(),
        json_schema_extra=SchemaExtraMetadata(
            title="Security",
            description="Dashboard login, data encryption and API access.",
        ).as_json_schema_extra(),
    )
    admin_username: str = Field(
        default="admin",
        min_length=1,
        json_schema_extra=SchemaExtraMetadata(
            title="Admin Username",
            description="Login for the dashboard and the management API.",
        ).as_json_schema_extra(),
    )
    admin_password: ApoloSecret = Field(
        ...,
        json_schema_extra=SchemaExtraMetadata(
            title="Admin Password",
            description="Password for the dashboard and the management API.",
        ).as_json_schema_extra(),
    )
    encryption_key: ApoloSecret = Field(
        ...,
        json_schema_extra=SchemaExtraMetadata(
            title="Encryption Key",
            description="Key that encrypts stored provider keys and virtual keys. "
            "It cannot be changed after installation: with a different key the "
            "gateway cannot read its data and does not start.",
            is_configurable=False,
        ).as_json_schema_extra(),
    )
    require_virtual_key: bool = Field(
        default=False,
        json_schema_extra=SchemaExtraMetadata(
            title="Require Virtual Key",
            description="Reject model requests that carry no virtual key. Keep it "
            "off to let other applications of the project use the gateway "
            "through integrations. It must be on when the ingress has no "
            "authentication.",
        ).as_json_schema_extra(),
    )


class BifrostAppInputs(AppInputs):
    preset: Preset = Field(
        ...,
        json_schema_extra=SchemaExtraMetadata(
            title="Resource Preset",
            description="At least 512 MB of memory. Memory bounds the request "
            "size the gateway accepts: about 40 MB of request body per 1 GB.",
        ).as_json_schema_extra(),
    )
    networking: BasicNetworkingConfig = Field(
        default_factory=BasicNetworkingConfig,
        json_schema_extra=SchemaExtraMetadata(
            title="Networking Settings",
            description="Configure network access and authentication.",
        ).as_json_schema_extra(),
    )
    storage: SQLiteStorage | PostgresStorage = Field(
        default_factory=SQLiteStorage,
        json_schema_extra=SchemaExtraMetadata(
            title="Storage",
            description="Where the gateway keeps its configuration and request "
            "logs. It cannot be changed after installation.",
            is_configurable=False,
        ).as_json_schema_extra(),
    )
    security: BifrostSecurity
    vllm_backends: list[VLLMBackend] = Field(
        default_factory=list,
        json_schema_extra=SchemaExtraMetadata(
            title="vLLM Backends",
            description="vLLM applications served through the gateway.",
        ).as_json_schema_extra(),
    )
    providers: list[ExternalProvider] = Field(
        default_factory=list,
        json_schema_extra=SchemaExtraMetadata(
            title="External Providers",
            description="Hosted providers served through the gateway. Providers "
            "are managed here: one added in the dashboard is removed on the next "
            "restart.",
        ).as_json_schema_extra(),
    )

    @model_validator(mode="after")
    def _require_auth(self) -> t.Self:
        auth = self.networking.ingress_http.auth
        if isinstance(auth, NoAuth) and not self.security.require_virtual_key:
            msg = "An ingress without authentication requires virtual keys"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _require_distinct_entries(self) -> t.Self:
        backends = [backend.identity for backend in self.vllm_backends]
        if len(set(backends)) != len(backends):
            msg = "The same vLLM backend is listed more than once"
            raise ValueError(msg)
        providers = [provider.identity for provider in self.providers]
        if len(set(providers)) != len(providers):
            msg = "The same provider API key is listed more than once"
            raise ValueError(msg)
        return self


class BifrostAppOutputs(AppOutputs):
    gateway_api: ServiceAPI[RestAPI] | None = Field(
        default=None,
        json_schema_extra=SchemaExtraMetadata(
            title="Gateway API",
            description="OpenAI-compatible API of the gateway for every "
            "configured model.",
        ).as_json_schema_extra(),
    )
    chat_apis: list[ServiceAPI[OpenAICompatChatAPI]] = Field(
        default_factory=list,
        json_schema_extra=SchemaExtraMetadata(
            title="Chat APIs",
            description="Chat API of each vLLM model served through the gateway.",
        ).as_json_schema_extra(),
    )
    admin_username: str | None = Field(
        default=None,
        json_schema_extra=SchemaExtraMetadata(
            title="Admin Username",
            description="Login for the dashboard and the management API.",
        ).as_json_schema_extra(),
    )
    admin_password: ApoloSecret | None = Field(
        default=None,
        json_schema_extra=SchemaExtraMetadata(
            title="Admin Password",
            description="Password for the dashboard and the management API.",
        ).as_json_schema_extra(),
    )
