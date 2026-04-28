# Lint, Template, Diff (CI gate)

> **Purpose**: The static-validation triad every chart must pass before merge — `helm lint`, `helm template | kubeconform`, `helm diff upgrade`
> **MCP Validated**: 2026-04-26

## When to Use

- Local: before `git push` for any chart change
- CI: blocking job in `.github/workflows/ci.yml` (DESIGN §3 entry #18)
- Pre-deploy: `helmfile diff` before any prod-ish apply

## The Three Checks

### 1. `helm lint` — chart-level sanity

Catches: missing values, malformed Chart.yaml, broken templates.

```bash
helm lint helm/backend -f helm/backend/values-dev.yaml
helm lint helm/backend -f helm/backend/values-prod.yaml
```

Lint each values file separately — they exercise different template branches.

### 2. `helm template | kubeconform` — schema validation

`helm template` renders without a cluster; `kubeconform` validates the YAML against published K8s OpenAPI schemas.

```bash
helm template backend helm/backend -f helm/backend/values-dev.yaml \
  | kubeconform -strict -summary -schema-location default \
      -schema-location 'https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json' \
      -kubernetes-version 1.31.0 -
```

`-schema-location` with the CRDs-catalog URL handles ServiceMonitor, Rollout, AnalysisTemplate, SealedSecret.

### 3. `helm diff upgrade` — pre-apply preview

Shows the precise patch a `helm upgrade` would send.

```bash
# Install the plugin once
helm plugin install https://github.com/databus23/helm-diff

helm diff upgrade backend helm/backend -f helm/backend/values-dev.yaml -n sre-copilot
helmfile diff                       # all releases at once
```

## CI Wiring

```yaml
# .github/workflows/ci.yml (excerpt)
jobs:
  helm-validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: azure/setup-helm@v4
        with: { version: v3.16.0 }
      - name: Install helmfile + kubeconform
        run: |
          curl -sSL https://github.com/helmfile/helmfile/releases/download/v0.169.0/helmfile_0.169.0_linux_amd64.tar.gz | tar xz -C /usr/local/bin helmfile
          curl -sSL https://github.com/yannh/kubeconform/releases/download/v0.6.7/kubeconform-linux-amd64.tar.gz | tar xz -C /usr/local/bin kubeconform
      - name: Helm lint (every chart, every values file)
        run: |
          for chart in helm/*/ helm/platform/*/ helm/observability/*/; do
            for vfile in $(ls "$chart"values*.yaml 2>/dev/null); do
              helm lint "$chart" -f "$vfile"
            done
          done
      - name: Render + kubeconform
        run: |
          helmfile template | kubeconform -strict -summary \
            -schema-location default \
            -schema-location 'https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json' \
            -kubernetes-version 1.31.0 -
```

## Catching Common Bugs Statically

| Bug | What catches it |
|-----|-----------------|
| `image.tag` empty → `backend:` (broken ref) | helm lint (unless template-side defaulted) |
| Missing required value | helm lint with `required` in template |
| Probe path typo | kubeconform won't catch (no schema for value); add unit test |
| Indentation nesting error | helm template fails to render |
| Unknown `apiVersion` (e.g., `policy/v1beta1` after deprecation) | kubeconform `-strict` |
| ResourceQuota would deny | helm diff (vs cluster) — only on running cluster |

## Local Dev Loop

```bash
# Fast feedback while editing helm/backend/templates/deployment.yaml
helm lint helm/backend && helm template backend helm/backend -f helm/backend/values-dev.yaml | head -80
```

For rapid iteration use `tilt up` (Tiltfile from DESIGN §4.9) — it re-renders + re-applies on file save.

## Configuration

| Tool | Recommended Flag | Why |
|------|------------------|-----|
| `helm lint` | `-f values-{env}.yaml` per env | Lint exercises each branch |
| `kubeconform` | `-strict` | Reject extra/unknown fields |
| `kubeconform` | `-kubernetes-version 1.31.0` | Match kind cluster |
| `helm diff upgrade` | `--detailed-exitcode` | Exit 2 if changes — gate CD |
| `helmfile diff` | `--detailed-exitcode --suppress-secrets` | Same + redact |

## Example Usage

```bash
# Pre-PR local
make lint                            # delegates to: helmfile lint + render | kubeconform
helmfile diff                        # show what `apply` would do

# CI failure example
$ kubeconform -strict ...
Summary: 24 resources found in 1 file - Valid: 23, Invalid: 1, Errors: 0
backend ServiceMonitor: failed validation: ServiceMonitor.spec.endpoints[0].interval expected string, got int
```

## See Also

- concepts/helmfile-model.md — `helmfile lint`, `template`, `diff` subcommands
- patterns/common-pitfalls.md — what lint can't catch
