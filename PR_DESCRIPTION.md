# Phase Up: Sprint 1–4 reliability, governance, and observability improvements

## Summary

This PR transforms VidCast from a working-but-bare microservices deployment into a
production-grade platform: it adds GitOps delivery, policy-as-code governance,
supply-chain integrity, SLO-based alerting, secret externalisation, autoscaling,
zero-trust networking, and cost visibility — without changing the app's behaviour.
Every new control ships **safe-by-default** (feature flags OFF, Kyverno in Audit),
so the running system is unaffected until each control is deliberately switched on.

## What changed (by sprint)

### Sprint 1 — foundations
- **A10 Kustomize overlays** — `k8s/base` + `k8s/overlays/{dev,prod}`; the old
  per-service `manifest/` YAML is replaced by a composable base/overlay tree.
- **A9 External Secrets Operator** — secrets move out of files into **AWS SSM
  Parameter Store**, pulled in via ESO + IRSA (no long-lived AWS keys, nothing in
  git). New `terraform/modules/external-secrets`.

### Sprint 2 — reliability
- **A4 gunicorn** — production WSGI server for auth + gateway (replaces the
  single-threaded dev server).
- **A1 transactional outbox** — a single-replica relay publishes upload events
  durably, surviving a broker outage at upload time (flag `OUTBOX_ENABLED`, default off).
- **A3 retry/DLQ topology** — bounded retries + per-pipeline dead-letter queues;
  a poison message is retried then dead-lettered instead of crash-looping a consumer.
- **A2 idempotent consumers** — Redis claim-once (`SET NX EX`) with release-on-retry,
  so a redelivered message can't double-convert or double-email (flag `IDEMPOTENCY_ENABLED`).
- **A7 KEDA + HPA** — converter scales to zero on an empty queue and up on depth;
  gateway gets a CPU HPA.
- **A6 NetworkPolicies** — default-deny + per-service allow rules (zero-trust);
  VPC-CNI network-policy agent enabled in Terraform.

### Sprint 3 — governance
- **B1 Argo CD GitOps** — `Application` CRDs: dev auto-syncs, prod is manual-sync
  (the human merge/sync is the approval gate). See `GITOPS.md`.
- **B2 Kyverno policy-as-code** — 7 `ClusterPolicies` (latest-tag, requests/limits,
  non-root, seccomp, labels, privileged, image-verify) — **all Audit mode**.

### Sprint 4 — polish + hardening
- **Gap-fix** — seccomp `RuntimeDefault` on every workload, datastore resource
  requests/limits + labels + securityContext, pinned image tags (closes the B2
  Audit→Enforce prerequisites; 5/6 policies now clean).
- **B4 SLO burn-rate alerting** — fixed the M-2 metrics gap (gateway `/metrics`,
  converter/notification metrics servers, RabbitMQ `rabbitmq_prometheus`), then built
  multi-window multi-burn-rate `PrometheusRules` + an error-budget Grafana dashboard
  for 3 SLOs (availability, conversion latency, end-to-end success). See `SLO.md`.
- **A8 supply chain** — hardened ECR (immutable tags, scan-on-push, lifecycle) in
  Terraform; documented the cosign keyless signing identity. See `SUPPLY_CHAIN.md`.
- **B5 cosign verification** — Kyverno `verify-images` activated for both registries
  (Docker Hub + ECR) against the real signing identity, **Audit**; Sigstore egress
  NetworkPolicy for Kyverno.
- **B3 Kubecost** — FinOps cost visibility (OSS, reuses the existing Prometheus),
  headline **cost-per-conversion** dashboard.

## Breaking changes

**None.** The transactional outbox (`OUTBOX_ENABLED`) and idempotency
(`IDEMPOTENCY_ENABLED`) default **off**; Kyverno policies are all **Audit** (report,
never block); `verify-images` reports our images as unsigned until CI signing lands
(expected). Existing endpoints and behaviour are unchanged.

## Cost impact

**$0 beyond the existing cluster.** No CMK (AES256 AWS-managed), Parameter Store
(free standard tier, not Secrets Manager), Kubecost OSS, all observability on the
existing node. No new standing AWS charge.

## What follows this PR

- **CI supply-chain steps** (SBOM + SARIF + cosign keyless signing + SLSA
  provenance) — diffs in `SUPPLY_CHAIN.md`; unlocks B5 → Enforce.
- **B1 CD gate-migration** (`cd.yml` → tag-bump-PR for Argo) — diff in `GITOPS.md` §6.
- **Kyverno Audit → Enforce** promotion (per-policy, after reports are clean;
  `require-non-root` needs a mongo/postgres exclude).
- **Runtime verification** of every config-verified component on the next cluster
  bring-up (full checklist in `DEPLOYMENT_HANDOVER.md`).

## Node resource budget

**~81% idle** on the **dev overlay** (1-replica backends) with all add-ons including
Kubecost. Prod overlay + Kubecost breaches the 90% gate on the single 2-vCPU node,
so Kubecost runs on the dev footprint (or scale-to-zero between analyses) — a
conscious, documented decision.
