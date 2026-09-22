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
