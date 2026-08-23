# rain

A Helm chart for [RAIN](../../README.md) covering the same deployment
shapes as this repo's `docker-compose.yml` / `docker-compose.minimal.yml`
-- see [`docs/architecture.md`](../../docs/architecture.md#deployment-shapes)
for the underlying design (this chart doesn't introduce anything new
there, just a second way to express the same axes).

No public image is published. Build one yourself first:

```sh
docker build -t <your-registry>/rain-app:latest ./backend
docker push <your-registry>/rain-app:latest
```

The same image runs both the `app` and `worker` workloads (different
`command:`, same as the two Docker images already being one Dockerfile
with two entrypoints -- see `backend/Dockerfile`/`docker-compose.yml`).

## Default deployment (two workloads, bundled or external Postgres)

```sh
helm install rain ./charts/rain \
  --set appSecretKey=$(openssl rand -base64 48) \
  --set image.repository=<your-registry>/rain-app \
  --set ingress.host=rain.example.com \
  --set database.url=postgresql://user:password@your-db-host:5432/rain
```

Or, for a bundled single-replica Postgres instead (eval/dev only -- no
HA, no managed backups, see `values.yaml`'s own comment on
`database.embedded`):

```sh
helm install rain ./charts/rain \
  --set appSecretKey=$(openssl rand -base64 48) \
  --set image.repository=<your-registry>/rain-app \
  --set ingress.host=rain.example.com \
  --set database.embedded.enabled=true \
  --set database.embedded.password=$(openssl rand -base64 24)
```

This gets you: an `app` Deployment, a `worker` Deployment (syslog
listener + rule engine + notifications + calendar sweep + LDAP sync), a
PVC for local document storage, and an Ingress. Point your syslog-ng
destination at the `<release>-syslog` Service's external address --
`kubectl get svc` after install, or see the post-install NOTES.

## Minimal mode (one workload, external DB, S3 storage)

```sh
helm install rain ./charts/rain -f charts/rain/values-minimal.yaml \
  --set image.repository=<your-registry>/rain-app \
  --set appSecretKey=$(openssl rand -base64 48) \
  --set database.url=postgresql://user:password@your-rds-endpoint:5432/rain \
  --set storage.s3.bucket=my-rain-documents \
  --set storage.s3.region=us-east-1
```

Folds the worker's duties into the `app` Deployment
(`worker.embedded: true`, i.e. `EMBED_WORKER=true`), skips the bundled
Postgres and PVC entirely, and drops the Ingress. See
`values-minimal.yaml`'s own comments.

## Values

See `values.yaml` for the complete, commented list. The load-bearing
ones:

| Key | What it does |
|---|---|
| `appSecretKey` | Required. Session-cookie signing + config-at-rest encryption key. |
| `database.url` | External Postgres DSN. Takes priority over `database.embedded.*`. |
| `database.embedded.enabled` | Bundle a single-replica Postgres instead (eval/dev only). |
| `database.enablePgvector` | Off for a managed Postgres role that can't `CREATE EXTENSION`, or that doesn't ship `vector` at all (e.g. standard RDS in AWS GovCloud). |
| `storage.s3.enabled` / `storage.s3.bucket` | Document storage in S3 (or S3-compatible) instead of a PVC. |
| `storage.persistence.enabled` | PVC for local document storage; ignored once `storage.s3.enabled` is true. |
| `worker.embedded` | Fold the worker's duties into the `app` Deployment instead of a separate one. |
| `ingress.enabled` / `ingress.host` | HTTP entry point. Disable for a cluster that already terminates TLS in front of RAIN some other way. |

## Verification note

This chart is written and periodically re-checked against the exact env
vars/behavior the app itself expects (`backend/src/rain/settings.py`,
`docker-compose.yml`) -- `helm lint`/`helm template` rendered and
inspected across the deployment shapes above (default, remote DB + S3
with a static key pair, remote DB + S3 on an IAM/instance-profile role,
minimal mode, `database.enablePgvector=false`), catching two settings
(`ENABLE_PGVECTOR`, `RAIN_DOMAIN`) that the app gained after this chart
was first written and that had gone unwired here since. It has still
never been installed against a real Kubernetes cluster -- there wasn't
one available in the environment this was built/reviewed in. Render it
locally before a real install to catch any templating mistakes of your
own:

```sh
helm template rain ./charts/rain --set appSecretKey=x --set database.url=postgresql://u:p@h:5432/rain
helm lint ./charts/rain
```
