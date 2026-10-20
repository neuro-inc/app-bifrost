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
| `vllm_backends` | Chat models of vLLM applications served through the gateway, with an optional API key. |
| `embedding_backends` | Embeddings models of vLLM or Text Embeddings Inference applications, with an optional API key. |
| `providers` | Hosted providers with their API keys, and the models of each to publish as chat or embeddings integrations. |

Providers are managed by the inputs only. The gateway runs with `source_of_truth: config.json`, so on every start it drops any provider or provider key that the inputs do not describe, including the ones added in the dashboard. Virtual keys, budgets and rate limits are managed in the dashboard and are kept.

## Outputs

| Output | Meaning |
| --- | --- |
| `app_url` | Dashboard. |
| `gateway_api` | OpenAI-compatible API for every configured model, `/v1`. |
| `openai_api` | The same API as one integration of type `OpenAICompatAPI`, with every published model and what it serves: `chat`, `completions` and `responses` for the vLLM chat backends, `chat` for the chat models of the providers, `embeddings` for the embeddings models. `model_prefixes` lists the providers, such as `openai/`: any model of a provider is served under its prefix. For applications that pick models themselves, such as OpenWebUI. |
| `chat_apis` | One chat API per chat model: the vLLM chat backends first, then the chat models listed for the providers. Usable as an integration by other applications. The model name carries the provider prefix, `vllm/` for the backends. |
| `embeddings_apis` | One embeddings API per embeddings model: the embeddings backends, then the embeddings models listed for the providers. |
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
- Renders one vLLM key per backend, chat and embeddings alike, with `allow_private_network: true` and a URL without the `/v1` suffix. Bifrost picks a key by the model name only, so one model name cannot be both a chat and an embeddings model.
- Writes the published model names to the top-level `gateway_models` value. The wrapper chart ignores it; the outputs processor reads it. Values without it, as written before this value existed, publish the vLLM backends as chat models.
- Names provider keys after their content: a readable prefix plus a hash of the provider and secret name, or of the vLLM URL, model and secret name. Reordering the inputs does not change the keys that virtual keys refer to.
- When no provider is configured at all, renders a disabled placeholder key for vLLM. The upstream chart cannot render an empty `providers` section, and without the section nothing is dropped.

## Behaviour worth knowing

- Request vLLM models as `vllm/<model>`, the form `/v1/models` lists. A bare name works only until it starts with a provider name: `openai/gpt-oss-20b` is sent to OpenAI, `vllm/openai/gpt-oss-20b` to the vLLM backend.
- Embeddings backends use the same `vllm` provider, so a Text Embeddings Inference model is requested as `vllm/<model>` too. Text Embeddings Inference has no `/v1/models`, so `/v1/models` does not list its models; requests still reach it.
- The gateway does not know what a model can do. A chat request for an embeddings model, or the reverse, is forwarded and the backend answers 404.
- Bifrost serves no embeddings from Anthropic, Groq, Perplexity, Cerebras and xAI, so the inputs reject embeddings models for them.
- Provider models are listed without the provider prefix: `gpt-4o-mini`, not `openai/gpt-4o-mini`. OpenRouter and Hugging Face are exempt because some of their own model IDs start with their name, for example `openrouter/auto`.
- A backend URL keeps the `base_path` of its integration: `/proxy/llama/` becomes `http://host:port/proxy/llama`, and Bifrost appends `/v1/...` to it.
- Other applications refer to `chat_apis` and `embeddings_apis` entries by position. The provider models come after the vLLM backends, so adding or removing a backend shifts the positions of the provider entries, and reordering the backends shifts the backend entries.
- A chat model also answers `/v1/completions` and `/v1/responses` on the same base URL when its backend does: vLLM, OpenAI.
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
