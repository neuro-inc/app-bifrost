# app-bifrost

[Bifrost](https://docs.getbifrost.ai/overview) AI gateway packaged as an Apolo application.

## Layout

- `charts/bifrost-app` is a wrapper chart. It pulls the upstream `bifrost` chart as a dependency and only carries the defaults the Apolo platform needs.
- `charts/bifrost-app/ci` holds one example of platform-generated values per storage mode.

## Versions

| Component | Version |
| --- | --- |
| Upstream chart `bifrost` | 2.1.43 |
| Image `maximhq/bifrost` | v2.2.6 |

## Chart defaults

| Value | Default | Why |
| --- | --- | --- |
| `bifrost.image.tag` | `v2.2.6` | The upstream chart has no default tag. |
| `bifrost.bifrost.authConfig` | enabled, `admin`, password from `BIFROST_ADMIN_PASSWORD` | The dashboard and management API always require the admin login. The password comes from a secret through `bifrost.env`. |
| `bifrost.bifrost.client.enforceAuthOnInference` | `false` | Apps in the same project call the gateway without a virtual key. Set it to `true` when the ingress has no platform authentication. |
| `bifrost.bifrost.client.dualCredentialConflictBehavior` | `prefer_vk` | Behind platform authentication a request carries the platform token in `Authorization` and the virtual key in `x-bf-vk`. |

Everything else is passed to the upstream chart unchanged, see its [values reference](https://docs.getbifrost.ai/deployment-guides/helm/values).

## Values the platform is expected to pass

- `bifrost.fullnameOverride`, `bifrost.resources`, `bifrost.tolerations`, `bifrost.affinity`, `bifrost.podLabels`.
- `bifrost.ingress` in the single-ingress form: `enabled`, `className`, `annotations`, `hosts`. Any nested map with an `enabled` key (for example `grpc`) switches the upstream chart to named ingresses and no Ingress is rendered for the host.
- `bifrost.bifrost.encryptionKeySecret` pointing at a key of the project secret. The key must never change after the first start: with a different key the server cannot decrypt its stored configuration and exits on startup.
- `bifrost.env` with two entries:
  - `BIFROST_ADMIN_PASSWORD` from the project secret;
  - `GOMEMLIMIT` set to about 90% of the memory limit, for example `460MiB` for `512Mi`.
- Storage: nothing for SQLite on a 10Gi volume, or `bifrost.storage.mode: postgres` with `bifrost.postgresql.external`. With the Apolo PostgreSQL app `sslMode` must be `require`; both the primary endpoint and PgBouncer work.
- vLLM backends under `bifrost.bifrost.providers.vllm`, one key per served model, with `network_config.allow_private_network: true`. The URL has no `/v1` suffix. An API key goes through `bifrost.bifrost.providerSecrets` and is referenced as `env.<NAME>`.

## Behaviour worth knowing

- Memory: about 200Mi idle plus roughly 20Mi per megabyte of request bodies processed at the same time. A 512Mi pod serves ordinary chat traffic, but one 20 MB body without `GOMEMLIMIT`, or three concurrent 10 MB bodies with it, get the pod OOM-killed. Size the preset for the largest payloads, or lower `bifrost.bifrost.client.maxRequestBodySizeMb` (default 100).
- Providers removed from values stay in the database and keep being routed. `bifrost.bifrost.sourceOfTruth: config.json` makes values authoritative for providers: removed entries disappear, and so does every provider added through the UI. Virtual keys are kept in both modes.
- A model can be requested by its bare name or as `vllm/<model>`; `/v1/models` lists the prefixed form.
- The management API accepts the admin login only. Through an ingress with platform authentication it is reachable from a browser session, not with a platform token.

## Local rendering

```shell
helm repo add bifrost https://maximhq.github.io/bifrost/helm-charts
helm dependency build charts/bifrost-app
helm lint charts/bifrost-app -f charts/bifrost-app/ci/sqlite-values.yaml
helm template bifrost charts/bifrost-app -f charts/bifrost-app/ci/postgres-vllm-values.yaml
```
