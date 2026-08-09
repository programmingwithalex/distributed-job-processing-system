# Manual EKS Deployment

This guide covers the first manual EKS deployment path for this project after the application images have already been pushed to Amazon ECR.

For this first pass, Postgres and RabbitMQ still run inside the cluster.

## Prerequisites

- `aws` installed and authenticated
- `eksctl` installed
- `kubectl` installed
- the API, Celery worker, and frontend images already pushed to ECR

## Set Environment Variables

```bash
CLUSTER_NAME=dist-jobs
AWS_REGION=us-east-1
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
IMAGE_TAG=$(git rev-parse HEAD)
```

## Cost Warning

Creating an EKS cluster starts billable AWS resources. In addition to worker nodes, the EKS control plane and any created load balancers can continue accruing charges until you delete them.

## Create The EKS Cluster (takes 15-20 minutes)

```bash
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
AWS_REGION=us-east-1
CLUSTER_NAME=dist-jobs

LATEST_EKS_VERSION=$(
  aws eks describe-cluster-versions \
    --region "$AWS_REGION" \
    --version-status STANDARD_SUPPORT \
    --query 'max_by(clusterVersions, &releaseDate).clusterVersion' \
    --output text
)

eksctl create cluster \
  --name "$CLUSTER_NAME" \
  --region "$AWS_REGION" \
  --version "$LATEST_EKS_VERSION" \
  --nodes 2 \
  --node-type t3.medium \
  --managed
```

## Update Kubeconfig

Tell local `kubectl` to talk to EKS cluster:

```bash
aws eks update-kubeconfig --region "$AWS_REGION" --name "$CLUSTER_NAME"
```

## Verify The Active Kubernetes Context Again

After updating kubeconfig and before applying resources, confirm `kubectl` is targeting the EKS cluster:

```bash
kubectl config current-context
```

## Deploy The Complete Application Stack

After Terraform has created the EKS cluster, this helper automates the remaining deployment steps: kubeconfig update, ingress-nginx installation, namespace and secret creation, ECR image publishing, Kustomize apply, and workload rollout checks.

```bash
bash infra/k8s/overlays/eks/deploy-eks-application-stack.sh
```

The helper runs the following steps in order:

1. Updates local kubeconfig for the `dist-jobs` EKS cluster so subsequent `kubectl` commands target the correct cluster.
2. Applies the ingress-nginx cloud manifest and waits for the ingress controller deployment to become available.
3. Creates the `dist-jobs` namespace idempotently.
4. Creates `application-secrets` if it does not already exist, including a generated Postgres password and the application database and broker connection values. On later runs, it preserves the existing Secret to avoid rotating database credentials.
5. Runs [publish-images.sh](./publish-images.sh), which builds and pushes any images missing for the selected full commit SHA and reuses immutable images that already exist.
6. Copies the Kubernetes manifests to a temporary workspace, injects the ECR registry and commit SHA, and applies the rendered EKS overlay without modifying tracked files.
7. Waits for Postgres, RabbitMQ, API, Celery worker, and frontend deployment rollouts to complete.
8. Verifies that the API, Celery worker, and frontend Deployments reference the exact expected immutable images.
9. Displays the application pods, Services, Ingress resources, and the ingress controller load balancer hostname for follow-up testing.

The manual steps below remain available for troubleshooting or when individual control over each step is required.

## Roll Back To A Published Commit

Dispatch the `Deploy EKS Environment` workflow and set `ref` to a previously deployed full commit SHA. The workflow checks out that commit, reuses its existing immutable ECR images, applies those exact image references, and verifies the completed rollout.

Normal deployments may use a branch, tag, or commit in `ref`; the workflow always resolves the checked-out ref to its full commit SHA before publishing. Use a full SHA for rollback so the selected release cannot move between dispatch and checkout.

Only select a commit that was successfully published under the immutable-image delivery flow. ECR rejects overwriting an existing commit tag, so rollback uses the original artifacts rather than rebuilding them.

## Destroy The EKS Application Stack

For the Terraform-managed EKS environment, use the ordered destroy helper rather than `eksctl`:

```bash
bash infra/k8s/overlays/eks/destroy-eks-application-stack.sh --confirm
```

The helper removes the application and ingress-nginx resources, waits for namespace cleanup, and then runs `terraform destroy`. The ECR repositories are configured for force deletion, so images do not block teardown. The persistent Terraform state bootstrap bucket is intentionally not destroyed.

## Install ingress-nginx

Install `ingress-nginx-controller` and then verify it's running:

```bash
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/cloud/deploy.yaml
kubectl rollout status deployment/ingress-nginx-controller -n ingress-nginx --timeout=300s
```

## Create The Namespace

Create the application namespace explicitly before creating the secret:

```bash
kubectl create namespace dist-jobs --dry-run=client -o yaml | kubectl apply -f -
```

## Create application-secrets

```bash
POSTGRES_PASSWORD=$(openssl rand -base64 24 | tr -dc 'A-Za-z0-9' | head -c 24)

kubectl create secret generic application-secrets \
  --namespace dist-jobs \
  --from-literal=POSTGRES_DB=jobs \
  --from-literal=POSTGRES_USER=postgres \
  --from-literal="POSTGRES_PASSWORD=${POSTGRES_PASSWORD}" \
  --from-literal="DATABASE_URL=postgresql+psycopg://postgres:${POSTGRES_PASSWORD}@postgres:5432/jobs" \
  --from-literal=CELERY_BROKER_URL='amqp://guest:guest@rabbitmq:5672//' \
  --dry-run=client -o yaml | kubectl apply -f -
```

## Apply The EKS Overlay

Apply the EKS overlay (which references `../../base` and layers EKS-specific customizations on top):

```bash
kubectl apply -k infra/k8s/overlays/eks
```

## Verify Deployment

Check pods:

```bash
kubectl get pods -n dist-jobs
```

Check services:

```bash
kubectl get svc -n dist-jobs
```

Check ingress resources (externally routed app entrypoints into system):

```bash
kubectl get ingress -n dist-jobs
```

Check application logs:

```bash
kubectl logs deployment/api -n dist-jobs
kubectl logs deployment/celery-worker -n dist-jobs
kubectl logs deployment/postgres -n dist-jobs
kubectl logs deployment/rabbitmq -n dist-jobs
```

Check ingress controller logs:

```bash
kubectl logs deployment/ingress-nginx-controller -n ingress-nginx
```

## Find The External Endpoint

Get the ingress controller service endpoint:

```bash
kubectl get svc -n ingress-nginx
```

Look for the external address on the `ingress-nginx-controller` service. AWS may take a few minutes to provision the load balancer and publish the endpoint.

## Test Frontend And API Access

Use the ingress controller ELB hostname directly:

```bash
INGRESS_HOST=$(kubectl get svc -n ingress-nginx ingress-nginx-controller -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')
```

Test the frontend:

```bash
curl "http://$INGRESS_HOST/"
```

Test the API health endpoint:

```bash
curl "http://$INGRESS_HOST/api/health"
```

Optional job submission test:

```bash
curl -X POST "http://$INGRESS_HOST/api/jobs" \
  -H "Content-Type: application/json" \
  -d '{"input_value":"hello-world","job_type":"echo"}'
```

## Cost Warning Before Cleanup

If you are done testing, delete the cluster promptly to avoid ongoing EKS, EC2, and load balancer charges.

Quick cleanup helper:

```bash
bash infra/k8s/overlays/eks/teardown-cluster.sh "$CLUSTER_NAME" "$AWS_REGION"
```

## Delete The Cluster

```bash
eksctl delete cluster --name "$CLUSTER_NAME" --region "$AWS_REGION"
```
