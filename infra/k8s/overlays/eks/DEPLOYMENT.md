# Manual EKS Deployment

This guide covers the first manual EKS deployment path for this project after the application images have already been pushed to Amazon ECR.

For this first pass, Postgres and RabbitMQ still run inside the cluster.

## Prerequisites

- `aws` installed and authenticated
- `eksctl` installed
- `kubectl` installed
- the API, Celery worker, and frontend images already pushed to ECR
- [kustomization.yaml](./kustomization.yaml) updated to the correct ECR image URLs and tag

## Set Environment Variables

```bash
CLUSTER_NAME=replace-me
AWS_REGION=us-east-1
AWS_ACCOUNT_ID=123456789012
IMAGE_TAG=v1
```

## Cost Warning

Creating an EKS cluster starts billable AWS resources. In addition to worker nodes, the EKS control plane and any created load balancers can continue accruing charges until you delete them.

## Create The EKS Cluster

```bash
eksctl create cluster \
  --name "$CLUSTER_NAME" \
  --region "$AWS_REGION" \
  --nodes 2 \
  --node-type t3.medium \
  --managed
```

## Update Kubeconfig

```bash
aws eks update-kubeconfig --region "$AWS_REGION" --name "$CLUSTER_NAME"
```

## Verify The Active Kubernetes Context Again

After updating kubeconfig and before applying resources, confirm `kubectl` is targeting the EKS cluster:

```bash
kubectl config current-context
```

## Install ingress-nginx

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
kubectl create secret generic application-secrets \
  -n dist-jobs \
  --from-literal=POSTGRES_DB=jobs \
  --from-literal=POSTGRES_USER=postgres \
  --from-literal=POSTGRES_PASSWORD=replace-me \
  --from-literal=DATABASE_URL='postgresql+psycopg://postgres:replace-me@postgres:5432/jobs' \
  --from-literal=CELERY_BROKER_URL='amqp://guest:guest@rabbitmq:5672//'
```

## Apply The EKS Overlay

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

Check ingress resources:

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

Set the load balancer hostname:

```bash
INGRESS_HOST=replace-me
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

## Delete The Cluster

```bash
eksctl delete cluster --name "$CLUSTER_NAME" --region "$AWS_REGION"
```
