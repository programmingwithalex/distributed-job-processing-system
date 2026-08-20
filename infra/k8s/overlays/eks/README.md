# EKS Image Publishing

Before applying the EKS overlay, publish the three application images to Amazon ECR.

Quick start:

```bash
bash infra/k8s/overlays/eks/publish-images.sh
```

The script publishes images under the current commit's full SHA. It does not modify the tracked Kustomize overlay.

For cluster creation, deployment, and EKS teardown, use [DEPLOYMENT.md](./DEPLOYMENT.md).

After Terraform creates the cluster, deploy the complete application stack with:

```bash
bash infra/k8s/overlays/eks/deploy-eks-application-stack.sh
```

The script updates kubeconfig, installs ingress-nginx, monitoring, and the pinned Argo CD control plane, creates the namespace and application secret when absent, publishes images to ECR, applies the EKS overlay, and waits for workload rollouts. It preserves an existing `application-secrets` Secret so rerunning it does not rotate database credentials.

Argo CD is installed into the `argocd` namespace. After the existing direct rollout is healthy, the script registers the manual-sync `dist-jobs-eks` Application with the selected ECR registry and immutable Git SHA. Automated synchronization is intentionally omitted so EKS changes require explicit review and manual approval.

### Refresh Kubeconfig After Cluster Recreation

An EKS cluster recreation receives a new control-plane endpoint. Before using `kubectl` or `helm` manually after a Terraform redeployment, refresh the local `dist-jobs` context:

```bash
aws eks update-kubeconfig --region us-east-1 --name dist-jobs
kubectl get nodes
```

The deploy and destroy scripts run this command automatically. A DNS error that names an older EKS endpoint indicates a stale kubeconfig; rerun the command before troubleshooting application resources.

## Monitoring

### Data Flow

```mermaid
flowchart LR
	client[Client request] --> api[API Pod\nFastAPI container]
	api -->|records counters and histograms| metrics[/metrics endpoint]
	service[API Service] --> api
	monitor[ServiceMonitor resource] -->|selects API Service\nport http| operator[Prometheus Operator Pod]
	operator -->|configures scrape target| prometheus[Prometheus Pod]
	prometheus -->|scrapes| service
	dashboard[Dashboard ConfigMap\ngrafana_dashboard: "1"] -->|watches and copies JSON| sidecar[Grafana dashboard sidecar\nin Grafana Pod]
	sidecar --> grafana[Grafana container\nin Grafana Pod]
	grafana -->|queries metrics| prometheus
	browser[Browser via kubectl port-forward] --> grafana
```

1. The FastAPI container in the API Pod records request counters and duration histograms, then exposes them at `/metrics`.
2. The `ServiceMonitor` is a Kubernetes custom resource, not a Pod. The Prometheus Operator watches it, selects the labeled API Service, and configures the Prometheus Pod to scrape the Service's `http` port at `/metrics`.
3. The Prometheus Pod stores the scraped time series. Grafana queries those time series through its internal Prometheus datasource to render the dashboard panels. The browser sends dashboard requests only to Grafana; Grafana acts as a proxy and sends each PromQL query to the internal Prometheus Service, so the browser never connects to the Prometheus Pod directly.
4. The Grafana Pod contains the Grafana container and a dashboard sidecar container. The sidecar watches labeled dashboard ConfigMaps, copies their JSON into Grafana's provisioning directory, and Grafana loads the dashboard definition.

The Git-provisioned `Distributed Jobs API` Grafana dashboard is defined in [../../monitoring/api-grafana-dashboard.yaml](../../monitoring/api-grafana-dashboard.yaml). Its **p95 Request Duration** panel estimates the request duration at or below which 95% of API requests completed during the rolling five-minute window. For example, a result of `0.5 s` means approximately 95% of observed requests completed in 500 ms or less.

The panel queries the API duration histogram with:

```promql
histogram_quantile(
	0.95,
	sum by (le) (rate(api_http_request_duration_seconds_bucket[5m]))
)
```

It aggregates all API routes, methods, and status codes into one whole-API latency signal. Use the dashboard's route-level request and error-rate panels to investigate a latency change by endpoint.

### Dashboard Provisioning

Grafana dashboards are stored as Kubernetes ConfigMaps, so their definitions are version-controlled with the application manifests. The Grafana sidecar watches ConfigMaps in every namespace and provisions the dashboard JSON they contain. A typical setup uses one ConfigMap per dashboard, such as [../../monitoring/api-grafana-dashboard.yaml](../../monitoring/api-grafana-dashboard.yaml).

Every dashboard ConfigMap in this deployment must include the label configured for the sidecar:

```yaml
labels:
	grafana_dashboard: "1"
```

This label tells the sidecar which ConfigMaps contain Grafana dashboards. The ConfigMap definitions survive Grafana Pod restarts, allowing the sidecar to restore the Git-managed dashboards. Grafana's own persistent storage is disabled here, so UI-only dashboard edits are not durable; make dashboard changes in the ConfigMap instead.

### Access Grafana

Grafana has no public ingress. Retrieve its generated `admin` password, then keep the following port-forward process running while you access [http://localhost:3000](http://localhost:3000):

```bash
kubectl get secret monitoring-grafana --namespace monitoring \
	--output jsonpath='{.data.admin-password}' | base64 --decode
echo

kubectl port-forward --namespace monitoring service/monitoring-grafana 3000:80
```

Sign in with username `admin`, then open the `Distributed Jobs API` dashboard. The `Healthy API Targets` panel should report at least `1` after Prometheus discovers the API ServiceMonitor.

Teardown when you only want to remove the ECR repositories:

```bash
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

bash infra/k8s/overlays/eks/teardown-ecr-repos.sh "$AWS_ACCOUNT_ID" us-east-1
```

## Prerequisites

- AWS CLI authenticated to the target AWS account
- Docker running locally
- permission to create and push to ECR repositories
- `ecr:PutImageTagMutability` permission, provided to GitHub Actions by the current Terraform bootstrap policy

## One-Time Publishing Flow

Run the helper from a Bash shell such as WSL:

```bash
bash infra/k8s/overlays/eks/publish-images.sh
```

The script uses the current Git commit's full 40-character SHA as its image tag. `IMAGE_TAG` must also be a full lowercase commit SHA when supplied explicitly.

The script will:

- create the `distributed-job-processing-system-api` ECR repository if missing
- create the `distributed-job-processing-system-celery-worker` ECR repository if missing
- create the `distributed-job-processing-system-frontend` ECR repository if missing
- enforce immutable tags on all three repositories
- reuse any images already published for the selected commit
- authenticate Docker to ECR
- build the `api`, `celery_worker`, and `frontend` images with Docker Compose
- tag and push those images to ECR

## Equivalent Manual Commands

```bash
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
AWS_REGION=us-east-1
IMAGE_TAG=$(git rev-parse HEAD)
ECR_REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
CLUSTER_NAME=dist-jobs

aws ecr create-repository --repository-name distributed-job-processing-system-api --image-tag-mutability IMMUTABLE --region "$AWS_REGION"
aws ecr create-repository --repository-name distributed-job-processing-system-celery-worker --image-tag-mutability IMMUTABLE --region "$AWS_REGION"
aws ecr create-repository --repository-name distributed-job-processing-system-frontend --image-tag-mutability IMMUTABLE --region "$AWS_REGION"

aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "$ECR_REGISTRY"

docker compose build api celery_worker frontend

docker tag distributed-job-processing-system-api:latest "$ECR_REGISTRY/distributed-job-processing-system-api:$IMAGE_TAG"
docker tag distributed-job-processing-system-celery_worker:latest "$ECR_REGISTRY/distributed-job-processing-system-celery-worker:$IMAGE_TAG"
docker tag distributed-job-processing-system-frontend:latest "$ECR_REGISTRY/distributed-job-processing-system-frontend:$IMAGE_TAG"

docker push "$ECR_REGISTRY/distributed-job-processing-system-api:$IMAGE_TAG"
docker push "$ECR_REGISTRY/distributed-job-processing-system-celery-worker:$IMAGE_TAG"
docker push "$ECR_REGISTRY/distributed-job-processing-system-frontend:$IMAGE_TAG"
```

The complete deployment helper copies the Kubernetes manifests to a temporary directory, injects the ECR registry and commit SHA there, applies that rendered overlay, and removes the temporary files. The committed [kustomization.yaml](./kustomization.yaml) intentionally retains deployment placeholders.
