# VidCast — Disaster Recovery Runbook

> Closes narrative gaps **I4** (no automated backup) and **P5** (no DR runbook).
> Companion to the durability work in `feature/improvement-sprint-1-durability-and-backup`.
>
> **Last restore test:** _NOT YET TESTED — fill in `YYYY-MM-DD` after performing the
> drill in §5._ A backup you have never restored is a hope, not a backup.

---

## 1. What this protects against

| Failure | Before | After this branch |
|---|---|---|
| Postgres pod restart | All registered users except the deploy.sh seed admin are lost (ephemeral pod fs) | Data persists on an EBS PVC (A11); also recoverable from nightly `pg_dump` |
| MongoDB PV loss / corruption | Every uploaded video + converted MP3 + outbox state gone permanently | Recoverable from the latest nightly `mongodump` (up to ~24h old) |
| Whole-cluster loss | App redeployable from Git via Argo CD, but **data gone** | App from Git + **data from S3 backups** = full recovery |

The application/control plane is already recoverable from Git (Argo CD). This
runbook covers the **stateful tier**, which Git cannot rebuild.

---

## 2. What is backed up, where, and how often

| Datastore | Tool | Schedule (UTC) | Destination | Format |
|---|---|---|---|---|
| MongoDB (videos, mp3s, outbox, metadata) | `mongodump --gzip --archive` | nightly **02:00** | `s3://vidcast-backups-501562869470/mongo/` | gzip archive |
| PostgreSQL (`authdb`) | `pg_dump \| gzip` | nightly **02:15** | `s3://vidcast-backups-501562869470/postgres/` | gzipped SQL |

- **Bucket:** `vidcast-backups-501562869470` — private, versioned, AES256-encrypted,
  created by `terraform/modules/storage`.
- **Retention:** 30 days (object + noncurrent-version lifecycle expiry).
- **Object keys** are timestamped: `mongo-YYYYMMDDTHHMMSSZ.archive.gz`,
  `postgres-YYYYMMDDTHHMMSSZ.sql.gz`.
- **Auth:** the CronJobs run as the `vidcast-backup` ServiceAccount (IRSA role
  `vidcast-cluster-backup-irsa`), which may only `s3:PutObject`/`ListBucket` on
  this one bucket — no other AWS access.

**Objectives**

| | Target | Why |
|---|---|---|
| **RPO** (max data loss) | **≤ 24h** | Nightly cadence. Tighten by adding a midday run if needed. |
| **RTO** (time to restore) | **≤ 2h** | Re-apply infra (~20m) + restore dumps (minutes–tens of minutes) + E2E verify. |

---

## 3. Prerequisites (provisioned by this branch)

1. **EBS CSI driver addon** — `terraform/modules/eks` (`aws_eks_addon.ebs_csi` +
   its IRSA role). Without it the Postgres PVC stays `Pending`.
2. **gp3 StorageClass `vidcast-ebs-gp3`** + **`postgres-pvc`** — `Helm_charts/Postgres`
   (`persistence.enabled=true`). `reclaimPolicy: Retain` so deleting the PVC does
   **not** delete the EBS volume.
3. **S3 backup bucket + backup IRSA role** — `terraform/modules/storage`.
4. **CronJobs + `vidcast-backup` SA** — `k8s/base/backup`, wired into both overlays.

> ⚠️ If `terraform/modules/storage`'s `bucket_prefix` is changed, update
> `BACKUP_BUCKET` in `k8s/base/backup/*-cronjob.yaml` and the bucket name in §2.

---

## 4. Restore procedures

> Run from a workstation with `kubectl` pointed at the cluster and the relevant
> secrets present (ESO-synced in prod, or `deploy.sh` in dev). Replace
> `<OBJECT>` with the chosen timestamped key from `aws s3 ls`.

### 4.1 Pick the backup to restore

```bash
aws s3 ls s3://vidcast-backups-501562869470/mongo/    --recursive | sort | tail
aws s3 ls s3://vidcast-backups-501562869470/postgres/ --recursive | sort | tail
```

### 4.2 Restore MongoDB

```bash
# 1. Pull the dump locally.
aws s3 cp s3://vidcast-backups-501562869470/mongo/<OBJECT> /tmp/mongo.archive.gz

# 2. Copy it into the running mongod pod.
kubectl cp /tmp/mongo.archive.gz mongodb-0:/tmp/mongo.archive.gz

# 3. Restore. --drop replaces existing collections with the backup's contents.
#    Omit --drop to merge instead of replace.
kubectl exec -it mongodb-0 -- mongorestore \
  --username="$MONGO_ROOT_USERNAME" --password="$MONGO_ROOT_PASSWORD" \
  --authenticationDatabase=admin \
  --gzip --archive=/tmp/mongo.archive.gz --drop
```

### 4.3 Restore PostgreSQL

```bash
# 1. Pull + decompress.
aws s3 cp s3://vidcast-backups-501562869470/postgres/<OBJECT> /tmp/pg.sql.gz
gunzip -f /tmp/pg.sql.gz   # -> /tmp/pg.sql

# 2. Ensure the schema exists (a fresh PVC is empty). The chart's init.sql /
#    deploy.sh seed runs on first boot; if restoring into a clean DB, the dump
#    itself recreates auth_user. Pipe it in:
POD=$(kubectl get pod -l name=postgres-pod -o jsonpath='{.items[0].metadata.name}')
kubectl exec -i "$POD" -- sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" psql -U pguser -d authdb' < /tmp/pg.sql
```

> If the restore target is a brand-new PVC, the bcrypt seed admin from
> `deploy.sh` must exist **or** be contained in the dump — otherwise log in with a
> user that the dump restored.

### 4.4 Verify integrity (do not skip)

```bash
# Postgres: row count + the seed admin is present and is a bcrypt hash.
kubectl exec -i "$POD" -- sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" psql -U pguser -d authdb -c \
  "SELECT count(*) FROM auth_user; SELECT email, left(password,4) AS hash_prefix, role FROM auth_user LIMIT 5;"'
# expect hash_prefix like $2a$ / $2b$ (bcrypt), NOT plaintext.

# Mongo: GridFS file counts are non-zero.
kubectl exec -it mongodb-0 -- mongo --quiet --eval \
  'print("videos="+db.getSiblingDB("videos")["fs.files"].count()+" mp3s="+db.getSiblingDB("mp3s")["fs.files"].count())'
```

### 4.5 Full pipeline smoke test

Log in (`baabalola@gmail.com / YourPassword123`) → upload a small video →
confirm conversion email → download the MP3. Restore is complete only when this
passes.

---

## 5. The DR drill (perform, then record the date at the top)

1. Trigger both backups on demand (don't wait for 02:00):
   ```bash
   kubectl create job --from=cronjob/mongo-backup    mongo-backup-drill-$(date +%s)
   kubectl create job --from=cronjob/postgres-backup pg-backup-drill-$(date +%s)
   ```
   Confirm a fresh object appears under each S3 prefix.
2. In a **non-prod** namespace/cluster (or a disposable re-apply), perform §4.2–4.4.
3. Time it end to end → record actual RTO. Update the **Last restore test** date.
4. File any surprises as issues; a runbook that drifted from reality is worse than none.

---

## 6. Follow-ups (out of scope for this branch)

- **Backup freshness alert (P5 monitoring):** a `PrometheusRule` that fires if no
  successful backup Job completed in the last 25h. The first time you learn
  backups stopped should not be the day you need one. (Needs a kube-state-metrics
  series on `kube_job_status_completion_time` filtered to the backup CronJobs.)
- **Metadata-only Mongo backups:** once P2 (S3 file storage) lands, files live in
  S3 with its own durability and the Mongo dump shrinks to metadata — much smaller
  and faster.
- **Cross-region copy** of the backup bucket for region-loss survivability
  (deliberately omitted now per the single-region cost decision).
