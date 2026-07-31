# EKS Image Publishing

Before applying the EKS overlay, publish the three application images to Amazon ECR.

Quick start:

```bash
bash infra/k8s/overlays/eks/publish-images.sh
```

Will also update `./kustomization.yaml` with ECR images after pushed.

For cluster creation, deployment, and EKS teardown, use [DEPLOYMENT.md](./DEPLOYMENT.md).

After Terraform creates the cluster, deploy the complete application stack with:

```bash
bash infra/k8s/overlays/eks/deploy-eks-application-stack.sh
```

The script updates kubeconfig, installs ingress-nginx, creates the namespace and application secret when absent, publishes images to ECR, applies the EKS overlay, and waits for workload rollouts. It preserves an existing `application-secrets` Secret so rerunning it does not rotate database credentials.

## Monitoring

The Git-provisioned `Distributed Jobs API` Grafana dashboard is defined in [monitoring/api-grafana-dashboard.yaml](./monitoring/api-grafana-dashboard.yaml). Its **p95 Request Duration** panel estimates the request duration at or below which 95% of API requests completed during the rolling five-minute window. For example, a result of `0.5 s` means approximately 95% of observed requests completed in 500 ms or less.

The panel queries the API duration histogram with:

```promql
histogram_quantile(
	0.95,
	sum by (le) (rate(api_http_request_duration_seconds_bucket[5m]))
)
```

It aggregates all API routes, methods, and status codes into one whole-API latency signal. Use the dashboard's route-level request and error-rate panels to investigate a latency change by endpoint.

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

## One-Time Publishing Flow

Run the helper from a Bash shell such as WSL:

```bash
bash infra/k8s/overlays/eks/publish-images.sh
```

The script uses the current Git commit's short SHA as its image tag. Supply `IMAGE_TAG` only when using another immutable identifier.

The script will:

- create the `distributed-job-processing-system-api` ECR repository if missing
- create the `distributed-job-processing-system-celery-worker` ECR repository if missing
- create the `distributed-job-processing-system-frontend` ECR repository if missing
- authenticate Docker to ECR
- build the `api`, `celery_worker`, and `frontend` images with Docker Compose
- tag and push those images to ECR
- update [kustomization.yaml](./kustomization.yaml) with the ECR image URLs and tag

## Equivalent Manual Commands

```bash
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
AWS_REGION=us-east-1
IMAGE_TAG=$(git rev-parse --short=12 HEAD)
ECR_REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
CLUSTER_NAME=dist-jobs

aws ecr create-repository --repository-name distributed-job-processing-system-api --region "$AWS_REGION"
aws ecr create-repository --repository-name distributed-job-processing-system-celery-worker --region "$AWS_REGION"
aws ecr create-repository --repository-name distributed-job-processing-system-frontend --region "$AWS_REGION"

aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "$ECR_REGISTRY"

docker compose build api celery_worker frontend

docker tag distributed-job-processing-system-api:latest "$ECR_REGISTRY/distributed-job-processing-system-api:$IMAGE_TAG"
docker tag distributed-job-processing-system-celery_worker:latest "$ECR_REGISTRY/distributed-job-processing-system-celery-worker:$IMAGE_TAG"
docker tag distributed-job-processing-system-frontend:latest "$ECR_REGISTRY/distributed-job-processing-system-frontend:$IMAGE_TAG"

docker push "$ECR_REGISTRY/distributed-job-processing-system-api:$IMAGE_TAG"
docker push "$ECR_REGISTRY/distributed-job-processing-system-celery-worker:$IMAGE_TAG"
docker push "$ECR_REGISTRY/distributed-job-processing-system-frontend:$IMAGE_TAG"
```

After pushing, make sure [kustomization.yaml](./kustomization.yaml) points at the correct ECR registry and image tag.
