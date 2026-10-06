# app-bifrost

[Bifrost](https://docs.getbifrost.ai/overview) AI gateway packaged as an Apolo application.

## Layout

- `charts/bifrost-app` is a wrapper chart. It pulls the upstream `bifrost` chart as a dependency and only carries the defaults the Apolo platform needs.

## Chart defaults

| Value | Default | Why |
| --- | --- | --- |
| `bifrost.image.tag` | `v2.2.6` | The upstream chart has no default tag. |
| `bifrost.bifrost.authConfig` | enabled, `admin`, password from `BIFROST_ADMIN_PASSWORD` | The dashboard and management API always require the admin login. The password comes from a secret through `bifrost.env`. |
| `bifrost.bifrost.client.enforceAuthOnInference` | `false` | Apps in the same project call the gateway without a virtual key. Set it to `true` when the ingress has no platform authentication. |
| `bifrost.bifrost.client.dualCredentialConflictBehavior` | `prefer_vk` | Behind platform authentication a request carries the platform token in `Authorization` and the virtual key in `x-bf-vk`. |

Everything else is passed to the upstream chart unchanged, see its [values reference](https://docs.getbifrost.ai/deployment-guides/helm/values).

## Values the platform is expected to pass

- `bifrost.fullnameOverride`, `bifrost.resources`, `bifrost.tolerations`, `bifrost.affinity`, `bifrost.podLabels`
- `bifrost.ingress` in the single-ingress form: `enabled`, `className`, `annotations`, `hosts`. Any nested map with an `enabled` key (for example `grpc`) switches the upstream chart to named ingresses and the host is not rendered.
- `bifrost.bifrost.encryptionKeySecret` and a `BIFROST_ADMIN_PASSWORD` entry in `bifrost.env`, both pointing at keys of the project secret.
- Storage: nothing for SQLite on a 10Gi volume, or `bifrost.storage.mode: postgres` with `bifrost.postgresql.external`. Use the direct PostgreSQL endpoint, not PgBouncer: migrations hold a session-level advisory lock.
- vLLM backends under `bifrost.bifrost.providers.vllm`, one key per served model, with `network_config.allow_private_network: true`. The URL has no `/v1` suffix.

`charts/bifrost-app/ci` holds one example per storage mode.

## Local rendering

```shell
helm repo add bifrost https://maximhq.github.io/bifrost/helm-charts
helm dependency build charts/bifrost-app
helm lint charts/bifrost-app -f charts/bifrost-app/ci/sqlite-values.yaml
helm template bifrost charts/bifrost-app -f charts/bifrost-app/ci/postgres-vllm-values.yaml
```
