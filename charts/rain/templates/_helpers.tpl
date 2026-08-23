{{/*
Standard name/label helpers (the usual `helm create` scaffold shape) plus
two chart-specific ones: rain.databaseUrl (picks database.url vs. the
embedded Postgres's in-cluster DNS name, same "external wins" precedence
Settings.database_url's own construction has in docker-compose.yml) and
rain.env (the env var list app and worker Deployments both need -- kept
in one place so the two can't drift the way two independently-maintained
copies eventually would).
*/}}

{{- define "rain.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "rain.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "rain.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "rain.labels" -}}
helm.sh/chart: {{ include "rain.chart" . }}
{{ include "rain.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "rain.selectorLabels" -}}
app.kubernetes.io/name: {{ include "rain.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "rain.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "rain.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{/*
"postgresql://user:pass@host:5432/rain" -- either database.url as-is,
or built from the embedded StatefulSet's own in-cluster Service DNS
name (<fullname>-postgres.<namespace>.svc.cluster.local) and the
credentials in database.embedded.*. Settings._normalize_driver (see
rain/settings.py) rewrites a bare "postgresql://" to the asyncpg-
specific driver URL on the app/worker side -- this helper deliberately
stays driver-agnostic, same division of responsibility the Compose
deployment's DATABASE_URL construction already has.
*/}}
{{- define "rain.databaseUrl" -}}
{{- if .Values.database.url -}}
{{ .Values.database.url }}
{{- else -}}
{{- printf "postgresql://%s:%s@%s-postgres:5432/%s" .Values.database.embedded.user .Values.database.embedded.password (include "rain.fullname" .) .Values.database.embedded.database -}}
{{- end -}}
{{- end -}}

{{/*
Shared env vars -- both the app Deployment and the worker Deployment
(when not folded into app via worker.embedded) need every one of
these except EMBED_WORKER, which only ever makes sense on the app
side (see values.yaml's own comment on worker.embedded) and is added
separately by deployment-app.yaml instead of here.
*/}}
{{- define "rain.commonEnv" -}}
- name: DATABASE_URL
  valueFrom:
    secretKeyRef:
      name: {{ include "rain.fullname" . }}
      key: database-url
- name: APP_SECRET_KEY
  valueFrom:
    secretKeyRef:
      name: {{ include "rain.fullname" . }}
      key: app-secret-key
- name: APP_PORT
  value: {{ .Values.app.port | quote }}
- name: SYSLOG_PORT
  value: {{ .Values.syslog.port | quote }}
- name: DEBUG
  value: {{ .Values.app.debug | quote }}
- name: RAIN_DOMAIN
  value: {{ .Values.ingress.host | default .Values.domain | quote }}
- name: ENABLE_PGVECTOR
  value: {{ .Values.database.enablePgvector | quote }}
{{- if .Values.storage.s3.enabled }}
- name: S3_BUCKET
  value: {{ .Values.storage.s3.bucket | quote }}
- name: S3_REGION
  value: {{ .Values.storage.s3.region | quote }}
- name: S3_ENDPOINT_URL
  value: {{ .Values.storage.s3.endpointUrl | quote }}
{{- if .Values.storage.s3.accessKeyId }}
- name: S3_ACCESS_KEY_ID
  valueFrom:
    secretKeyRef:
      name: {{ include "rain.fullname" . }}
      key: s3-access-key-id
- name: S3_SECRET_ACCESS_KEY
  valueFrom:
    secretKeyRef:
      name: {{ include "rain.fullname" . }}
      key: s3-secret-access-key
{{- end }}
{{- end }}
{{- end -}}
