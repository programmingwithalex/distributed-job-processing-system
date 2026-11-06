# Kubernetes Deployment

The application uses one Helm chart for every environment:

```text
infra/k8s/
├── argocd/                         Argo CD Application definitions
├── charts/distributed-jobs/         application Helm chart
│   ├── templates/                   Kubernetes resource templates
│   ├── values.yaml                  shared defaults
│   ├── values-local.yaml            k3d configuration and local-only secret
│   └── values-eks.yaml              immutable ECR release configuration
└── overlays/
    ├── local/                       k3d bootstrap and monitoring values
    └── eks/                         EKS bootstrap, teardown, and monitoring values
```

Helm renders the application resources, including the API Rollout, Services, ingress resources, database migration Job, ServiceMonitor, PrometheusRule, and Grafana dashboard. Argo CD renders the same chart from Git for both local and EKS Applications.

## Local k3d Deployment

Deploy the complete local stack from a Windows Terminal Ubuntu tab:

```bash
bash infra/k8s/environments/local/deploy-local-stack.sh
```

The helper recreates the k3d cluster, builds and imports local images, installs ingress-nginx, Prometheus, Grafana, Alertmanager, Argo Rollouts, and Argo CD, then installs the application chart with `values-local.yaml`.

The local application Secret is deliberately chart-managed only for k3d. EKS creates `application-secrets` outside Helm and does not store its credentials in Git.

### Manual Local Installation

```bash
k3d cluster delete distributed-jobs

docker compose build api celery_worker frontend

k3d cluster create distributed-jobs \
  --agents 1 \
  -p "8080:80@loadbalancer" \
  --k3s-arg "--disable=traefik@server:0"

k3d image import \
  distributed-job-processing-system-api:latest \
  distributed-job-processing-system-celery_worker:latest \
  distributed-job-processing-system-frontend:latest \
  --cluster distributed-jobs

kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/cloud/deploy.yaml
kubectl rollout status deployment/ingress-nginx-controller --namespace ingress-nginx --timeout=180s

helm upgrade --install monitoring oci://ghcr.io/prometheus-community/charts/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace \
  --version 87.21.0 \
  --values infra/k8s/environments/local/local-monitoring-values.yaml \
  --atomic \
  --wait \
  --timeout 10m

helm upgrade --install argo-rollouts oci://ghcr.io/argoproj/argo-helm/argo-rollouts \
  --namespace argo-rollouts \
  --create-namespace \
  --version 2.40.5 \
  --atomic \
  --wait \
  --timeout 10m

helm upgrade --install dist-jobs infra/k8s/charts/distributed-jobs \
  --namespace dist-jobs \
  --create-namespace \
  --values infra/k8s/charts/distributed-jobs/values-local.yaml \
  --wait \
  --wait-for-jobs \
  --timeout 10m
```

The frontend is available at <http://localhost:8080>; the API health endpoint is <http://localhost:8080/api/health>.

## Progressive Delivery

The API is an Argo Rollout. During an update, it sends `20%` and then `50%` of ingress traffic to the `api-canary` Service. At each step, Prometheus checks the canary-only HTTP 5xx rate twice at 30-second intervals. The release advances when the rate is at or below `5%`; two failed measurements roll back to the stable ReplicaSet.

```bash
kubectl get rollout api --namespace dist-jobs
kubectl get analysisrun --namespace dist-jobs
kubectl describe rollout api --namespace dist-jobs
```

## EKS Deployment

EKS infrastructure is provisioned through Terraform. The deployment helper installs the platform dependencies and renders the same chart with the Git-tracked `values-eks.yaml`:

```bash
bash infra/k8s/environments/eks/deploy-eks-application-stack.sh
```

Argo CD tracks the chart on `main`. An immutable-image promotion pull request changes `releaseTag` in `values-eks.yaml`; after review and merge, an operator manually synchronizes the EKS Application.

### PostgreSQL Persistence

PostgreSQL is a single-instance Deployment using `Recreate` updates and a dedicated `postgres-data` PVC. Its database files live at `/var/lib/postgresql/data/pgdata` on the mounted volume. Pod replacement reuses the claim; updates cause database downtime rather than running two database instances against the same storage. This is not database replication, high availability, or a backup.

Local Kubernetes uses its default StorageClass. EKS uses a dedicated `dist-jobs-postgres-gp3` StorageClass with a 10 GiB EBS claim, `WaitForFirstConsumer` placement, and a `Retain` reclaim policy. The claim and consuming Deployment share an Argo CD wave so delayed volume binding does not block pod creation. Bootstrap renders the storage resources alongside PostgreSQL before running migrations.

Helm uninstall and Argo CD pruning or Application deletion preserve the PVC. Explicit namespace deletion still deletes the claim. On EKS, the retained EBS volume remains after claim deletion and requires manual recovery or cleanup; it continues to incur charges and is not managed by Terraform. The existing EKS destroy workflow deletes the namespace and cluster, but does not remove this retained volume. Local cluster recreation deletes local storage and is not a persistence test.

**Existing deployments:** attaching a new PVC does not migrate database files from the old container. Before upgrading an existing deployment, stop job submissions and writers, export the database, and arrange a tested restore into the new volume. Do not apply this change to a database containing needed data without that migration plan. No live database migration is performed by the chart.

To verify persistence on a prepared deployment, record a completed job's ID and history, delete only the PostgreSQL pod, wait for its replacement to become ready, and verify the same job and history through the API. Confirm `postgres-data` remains `Bound` to the same PV. Do not delete the PVC, namespace, or cluster during this test.

### RabbitMQ Persistence

RabbitMQ uses a dedicated `rabbitmq-data` PVC, `Recreate` updates, and the stable node name `rabbit@rabbitmq` so replacement pods reopen the same broker database. Local Kubernetes uses its default StorageClass; EKS uses a 5 GiB `dist-jobs-rabbitmq-gp3` EBS claim with `Retain`. The claim has the same Helm and Argo CD retention protections as PostgreSQL. Explicit namespace deletion still removes the claim and leaves the retained EKS volume requiring manual cleanup.

Celery publishes persistent messages with broker confirmations. Queue storage survives pod replacement, but this single broker has downtime during replacement and is not a highly available cluster. Before replacing an existing ephemeral broker with the new PVC, stop submissions and dispatchers, drain queued work, and plan the broker-data migration; a new volume does not copy existing queues. Docker Compose also uses a named RabbitMQ volume and stable node name.

### Execution Delivery

The API commits a job and `job_dispatch_outbox` record atomically. The `job-dispatcher` Deployment delivers pending commands to RabbitMQ and records broker-confirmed delivery, retrying outages with capped backoff. Business retries reset that command transactionally rather than publishing from inside a worker. Migration `0009_job_dispatch_outbox` backfills queued and processing jobs from older releases; quiesce old writers during the upgrade because old API instances do not create dispatch records.

Workers hold a per-job PostgreSQL advisory lock on a dedicated connection while committing lifecycle transitions on their regular session. Redelivery of a terminal job does no work; concurrent delivery waits through a Celery retry; worker death releases the lock and late acknowledgement allows redelivery. An interrupted attempt that exhausted the persisted retry budget is dead-lettered. This does not guarantee exactly-once external effects or database high availability.

### Development Kafka Pipeline

Both EKS and local values enable one Apache Kafka KRaft broker, an `outbox-publisher` Deployment, and a `history-consumer` Deployment. The broker is a single combined broker/controller with plaintext listeners, no replica redundancy, and seven-day log retention. Do not treat it as a production Kafka service. Its EKS EBS volume is AZ-bound, so loss of node capacity in that AZ can leave the broker Pending until capacity returns.

Terraform installs the EBS CSI managed add-on with a narrowly scoped IRSA role. The Helm chart creates a `gp3` StorageClass and a 10 GiB `ReadWriteOnce` claim for the broker. Data survives broker Pod replacement, but deleting the StatefulSet deletes its claim and the StorageClass uses the `Delete` reclaim policy, so removing the development release also deletes its EBS volume. The EBS CSI add-on and volume incur AWS charges while provisioned.

The broker is reachable from the `dist-jobs` namespace at `kafka.dist-jobs.svc.cluster.local:9092`. Check its StatefulSet and claim with:

```bash
kubectl get statefulset,pod,pvc,storageclass --namespace dist-jobs
kubectl logs statefulset/kafka --namespace dist-jobs
```

The publisher and consumer start in Argo CD wave `1`, after migrations and the broker. They use the same worker image and release SHA as Celery, with the internal Kafka address supplied by `application-config`. The publisher creates `job-events.v1`; the consumer projects its events into PostgreSQL with event-ID deduplication and commits Kafka offsets only after database persistence. The EKS helper waits for all three background Deployments and verifies their worker images.

**Release prerequisite:** commit and publish a release containing the dispatcher and its migration, then promote that SHA through the existing image-promotion workflow before deploying these manifests to EKS. The currently pinned historical image is not updated by chart edits and does not contain the new dispatcher entry point. Do not apply this branch against that older release.

For a runtime check, submit a job and verify it completes with matching history, stop RabbitMQ temporarily and verify a submitted command remains pending, then recover the broker and verify delivery resumes. Redeliver a completed job ID and confirm its result, attempt count, and history do not change. Replace PostgreSQL and RabbitMQ pods separately and verify data and queued work survive. These tests require a running stack; Helm rendering does not prove recovery behavior. Full history rebuild is only possible if Kafka still retains all required events; the rebuild command refuses a truncated topic.

## Observability

Grafana is available through a local port-forward:

```bash
kubectl port-forward --namespace monitoring service/monitoring-grafana 3000:80
```

Retrieve the generated password with:

```bash
kubectl get secret monitoring-grafana --namespace monitoring \
  --output jsonpath='{.data.admin-password}' | base64 --decode
```
