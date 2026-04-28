# Common Helm + Helmfile Pitfalls

> **Purpose**: The bugs we've already paid for once. Reach for this when an upgrade behaves weirdly.
> **MCP Validated**: 2026-04-26

## When to Use

- Debugging a failed `helm upgrade` / `helmfile apply`
- Reviewing a chart PR — scan this list before approving

## Pitfalls

### 1. List values are REPLACED, not merged

```yaml
# values.yaml
env: [{ name: LOG_LEVEL, value: info }, { name: PORT, value: "8000" }]

# values-dev.yaml
env: [{ name: LOG_LEVEL, value: debug }]   # PORT is now MISSING
```

Fix: re-list every entry, or move env to a map and template into list:

```yaml
# values.yaml
env:
  LOG_LEVEL: info
  PORT: "8000"
```

```gotemplate
env:
{{- range $k, $v := .Values.env }}
  - { name: {{ $k }}, value: {{ $v | quote }} }
{{- end }}
```

### 2. `range` rebinds `.` — lose access to `.Values`

```gotemplate
{{- range .Values.env }}
  - name: {{ .name }}
    image: {{ $.Values.image.repository }}        # use $ for root
{{- end }}
```

### 3. Service `.spec.selector` is immutable

Changing pod labels in a chart that already has a Service breaks upgrade. Either change BOTH consistently or delete + reinstall the Service.

### 4. ConfigMap change does NOT roll Pods

Changing data in a ConfigMap won't restart Pods that mount it. Force a roll with a checksum annotation:

```yaml
# templates/deployment.yaml
spec:
  template:
    metadata:
      annotations:
        checksum/config: {{ include (print $.Template.BasePath "/configmap.yaml") . | sha256sum }}
```

### 5. CRD ordering: install before referencing

If chart A defines a CRD and chart B uses it, install A first. With Helmfile use `needs:`. With raw Helm:

```bash
helm install argo-rollouts ./argo-rollouts --wait
helm install backend ./backend            # safe: Rollout CRD exists
```

CRDs in `crds/` (capital folder) are NEVER upgraded by Helm — manage CRD upgrades manually.

### 6. `helm rollback` does NOT roll back CRDs or PVCs

CRDs in `crds/` are untouched. PVCs are retained by default. Plan for this.

### 7. `--wait` waits for `Available`, not `Healthy`

A Deployment is "Available" when MinAvailable Pods pass readiness. It does NOT mean traffic is real or that downstream connections work. Add a smoke test (Helm test or pytest) for end-to-end.

### 8. Helmfile `needs:` typo silently breaks order

```yaml
- name: backend
  needs:
    - sre-copilot/redis            # OK
    - srecopilot/redis             # SILENT: namespace doesn't exist
```

helmfile won't error; it just doesn't enforce the missing edge. Lint regex check in CI: `grep -E '^\s*-\s+\S+/\S+' helmfile.yaml | sort -u | check exists`.

### 9. `imagePullPolicy: Always` + kind = pull failure

kind nodes can't pull from your laptop's Docker daemon. Set:

```yaml
image:
  pullPolicy: Never
```

…and use `kind load docker-image sre-copilot/backend:dev`.

### 10. Tagging with `latest` defeats Helm rollback

If you tag images `latest`, every revision references the same tag → `helm rollback` doesn't actually change the running image. Always use immutable tags (git SHA, timestamp, semver).

### 11. SealedSecrets are namespace-scoped by default

A SealedSecret sealed for namespace `default` cannot be moved to `sre-copilot` without re-sealing (or sealing with `--scope cluster-wide`). For SRE Copilot we seal per-namespace.

### 12. Subchart values must nest under the dependency name

```yaml
# Chart.yaml
dependencies:
  - name: redis
    repository: ...
```

```yaml
# parent values.yaml
redis:                          # MUST match `name:` above
  master:
    persistence:
      enabled: false
```

### 13. `--atomic` masks the real error

`--atomic` rolls back on failure, deleting the failed Pods. You then can't `kubectl logs` them. Run failed deploy without `--atomic` to debug, then re-add.

### 14. Helm's "post-upgrade" hook runs even if upgrade is a no-op

Side-effecting post-upgrade hooks (cache warm, migration) fire on every `helmfile apply`. Use `helm.sh/hook-delete-policy: before-hook-creation,hook-succeeded` and idempotent commands.

### 15. `helmfile apply` (vs `sync`) skips releases with no diff

This is usually what you want, but it means a chart-template change without a values change can be missed if the rendered diff is empty (rare, but happens with Always-pull side-effecting CRDs). Use `helmfile sync` to force.

## Quick Sanity Checklist

```text
[ ] All charts: helm lint passes for every values-*.yaml
[ ] Every Deployment: checksum/config annotation if it has a ConfigMap envFrom
[ ] Every helmfile release with a runtime dep: needs: declared
[ ] No imagePullPolicy: Always in values-dev.yaml
[ ] No "latest" tags anywhere
[ ] CRD-consuming charts: depend on CRD-installing chart in helmfile
```

## See Also

- patterns/lint-template-diff.md — what static checks DO catch
- concepts/lifecycle-and-hooks.md — hook delete policies
- concepts/values-inheritance.md — list-vs-map merge semantics
