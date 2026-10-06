# app-bifrost

[Bifrost](https://docs.getbifrost.ai/overview) AI gateway packaged as an Apolo application.

## Layout

- `charts/bifrost-app` is a wrapper chart. It pulls the upstream `bifrost` chart as a dependency and only carries the defaults the Apolo platform needs.
- `charts/bifrost-app/ci` holds one example of generated values per storage mode.
- `.apolo/applications.yaml` registers the application in the Apolo catalog.
- `.apolo/src/apolo_apps_bifrost` holds the input and output types, the processor that turns inputs into chart values, the processor that turns chart values into outputs, and the generated JSON schemas.

## Versions

| Component | Version |
| --- | --- |
| Upstream chart `bifrost` | 2.1.43 |
| Image `maximhq/bifrost` | v2.2.6 |

## Inputs

| Input | Meaning |
| --- | --- |
| `preset` | Resources of the gateway. At least 512 MB of memory. |
| `networking` | Ingress and its authentication. |
| `storage` | SQLite on a volume, or a PostgreSQL user of the Apolo PostgreSQL application. Fixed after installation. |
| `security.admin_username`, `security.admin_password` | Login for the dashboard and the management API. |
| `security.encryption_key` | Key that encrypts stored data. Fixed after installation. |
| `security.require_virtual_key` | Reject model requests without a virtual key. Required when the ingress has no authentication. |
| `vllm_backends` | vLLM applications served through the gateway, with an optional API key. |
| `providers` | Hosted providers with their API keys. |

Providers are managed by the inputs only. The gateway runs with `source_of_truth: config.json`, so on every start it drops any provider or provider key that the inputs do not describe, including the ones added in the dashboard. Virtual keys, budgets and rate limits are managed in the dashboard and are kept.

## Outputs

| Output | Meaning |
| --- | --- |
| `app_url` | Dashboard. |
| `gateway_api` | OpenAI-compatible API for every configured model, `/v1`. |
| `chat_apis` | One chat API per vLLM model, usable as an integration by other applications. The model name carries the `vllm/` prefix. |
| `admin_username`, `admin_password` | Dashboard login. |

## Chart defaults

| Value | Default | Why |
| --- | --- | --- |
| `bifrost.image.tag` | `v2.2.6` | The upstream chart has no default tag. |
| `bifrost.bifrost.sourceOfTruth` | `config.json` | Providers follow the inputs, see above. |
| `bifrost.bifrost.authConfig` | enabled, `admin`, password from `BIFROST_ADMIN_PASSWORD` | The dashboard and management API always require the admin login. The password comes from a secret through `bifrost.env`. |
| `bifrost.bifrost.client.enforceAuthOnInference` | `false` | Apps in the same project call the gateway without a virtual key. |
| `bifrost.bifrost.client.dualCredentialConflictBehavior` | `prefer_vk` | Behind platform authentication a request carries the platform token in `Authorization` and the virtual key in `x-bf-vk`. |

## What the values processor does

- Sets `fullnameOverride` to `bifrost-<app id>`; the outputs are derived from it.
- Passes the ingress in the single-ingress form. Any nested map with an `enabled` key (for example `grpc`) switches the upstream chart to named ingresses and no Ingress is rendered for the host.
- Sets `GOMEMLIMIT` to 90% of the memory limit and `maxRequestBodySizeMb` to 1 MB per 25 MiB of memory, at most 100. Request bodies are buffered with about 20x amplification: without these a 512Mi pod is OOM-killed by a single 20 MB request.
- References every secret by key: admin password, encryption key, PostgreSQL password and provider API keys. No secret value is written to the values.
- Connects to PostgreSQL with `sslMode: require`.
- Renders one vLLM key per backend with `allow_private_network: true` and a URL without the `/v1` suffix.
- Names provider keys after their content: a readable prefix plus a hash of the provider and secret name, or of the vLLM URL, model and secret name. Reordering the inputs does not change the keys that virtual keys refer to.
- When no provider is configured at all, renders a disabled placeholder key for vLLM. The upstream chart cannot render an empty `providers` section, and without the section nothing is dropped.

## Behaviour worth knowing

- Request vLLM models as `vllm/<model>`, the form `/v1/models` lists. A bare name works only until it starts with a provider name: `openai/gpt-oss-20b` is sent to OpenAI, `vllm/openai/gpt-oss-20b` to the vLLM backend.
- The management API accepts the admin login only. Through an ingress with platform authentication it is reachable from a browser session, not with a platform token.
- With platform authentication on the ingress a virtual key goes in the `x-bf-vk` header, because `Authorization` carries the platform token.

## Development

```shell
make setup
make lint
make test-unit
make test-helm
make test-chart
make gen-types-schemas
```

`make test-chart` renders the chart with the values the processor generates and needs `helm` with the chart dependencies built by `make test-helm`.
