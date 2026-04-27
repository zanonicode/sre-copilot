# ADR-001: kind-native runtime from day 1 (no docker-compose detour)

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-04-26 |
| **Supersedes** | Sprint-1 plan §7 (which proposed docker-compose first) |

---

## Context

The project is a portfolio signal for Kubernetes / SRE / platform-engineering literacy. The original sprint plan proposed a docker-compose foundation followed by a kind migration in Sprint 2. This double-builds the deployment artefact for no narrative gain.

## Choice

Use kind from day 1. Tilt closes the inner-loop developer experience that compose was supposed to solve (file-watch → image rebuild → pod replace). All workloads are deployed via Helm from the first commit; ArgoCD is layered on in Sprint 3.

## Rationale

- Compose hides exactly what we want to demonstrate: Pods, Services, Ingress, NetworkPolicy, PDB, Rollouts.
- A mid-project rewrite from compose to Kubernetes is throwaway work that competes with Sprint-2 deliverables.
- Tilt provides hot-reload for backend/frontend equivalent to compose's UX.
- Reviewers never see compose — they see `make up` → kind.

## Alternatives Rejected

1. **Docker Compose first, kind later (original plan).** Rejected: doubles work, hides the signal.
2. **k3d instead of kind.** Rejected: kind has stronger Docker Desktop integration on macOS and is the conventional choice in CNCF training material reviewers will recognise.
3. **minikube.** Rejected: heavier resource footprint, less Docker-native, slower cold start.

## Consequences

- Sprint 1 must include a minimal Helm chart (not "just run uvicorn") — slightly higher Sprint-1 cost.
- All developers need Docker Desktop / OrbStack 4.30+. Documented in README prerequisites.
- Tilt becomes a required (not optional) inner-loop tool — `Tiltfile` ships in repo root.
