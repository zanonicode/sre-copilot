# ADR-007: Configurable Docker host bridge CIDR (portability across container runtimes)

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-04-26 (post-Sprint-2 portability hardening) |

---

## Context

Backend pods reach Ollama on the host via a NetworkPolicy egress rule that allows TCP 11434 to a specific IP block — the Docker host bridge CIDR. The `host.docker.internal` hostname resolves to different IPs depending on the container runtime in use:

| Runtime | `host.docker.internal` resolves to | Bridge CIDR |
|---------|-------------------------------------|-------------|
| Docker Desktop (macOS) | `192.168.65.254` | `192.168.65.0/24` |
| OrbStack | `198.19.249.1` | `198.19.249.0/24` |
| Colima | `192.168.106.1` | `192.168.106.0/24` |
| Linux native Docker | `172.17.0.1` | `172.17.0.0/16` |

After Sprint 1, the CIDR was a chart value with no override path through the deploy toolchain. This made the demo silently fail on OrbStack, Colima, and Linux — connection timeouts with no obvious cause.

## Choice

Three-part solution:

1. **Helm value `hostBridgeCIDR`** in `helm/platform/ollama-externalname/values.yaml` (default `192.168.65.0/24`), consumed by the NetworkPolicy template in the same chart. Single-responsibility: the chart that defines the ExternalName bridge owns the CIDR for it.
2. **Helmfile env-templating** for zero-friction override: `value: {{ env "HOST_BRIDGE_CIDR" | default "192.168.65.0/24" }}` in the `ollama-externalname` release stanza.
3. **`make detect-bridge` target** that spins up a one-shot Alpine container to resolve `host.docker.internal` and computes the `/24` CIDR automatically.

## Rationale

1. **Portability is a real success-criterion concern.** NFR7 says a stranger reproduces in <10 min. "Stranger" includes OrbStack users and Linux developers.
2. **Auto-detect via Docker is more reliable than a hardcoded table.** `make detect-bridge` works on unknown future runtimes without a doc update.
3. **Single-responsibility.** `ollama-externalname` owns the bridge concept end-to-end. The `networkpolicies` chart is strictly runtime-agnostic.

## Alternatives Rejected

1. **Hardcode `0.0.0.0/0` egress for port 11434.** Rejected: defeats the NetworkPolicy entirely.
2. **Detect CIDR at chart-render time via Helm lookup function.** Rejected: `helm lookup` is disabled in offline rendering; makes `helm template` non-deterministic.
3. **Per-runtime values files.** Rejected: proliferates files that diverge silently; doesn't help auto-detect.
4. **Document the variation in README only.** Rejected: re-introduces the silent-failure mode for users who skim the README.

## Consequences

- (+) Demo works on 4 known runtimes out of the box with a single env-export step.
- (+) Single point of override (`HOST_BRIDGE_CIDR` env var) is easy to document and persist via direnv `.envrc`.
- (+) `networkpolicies` chart is fully runtime-agnostic.
- (–) Adds one prerequisite step for non-Docker-Desktop users. Mitigated by README "Configuring the Docker host bridge" section with the runtime table and `make detect-bridge`.
