# Kubernetes Overlays

This directory contains environment-specific Kubernetes configurations built on top of the shared manifests in `../base`.

## Structure

```text
overlays/
├── README.md
├── local/
│   ├── deploy-local-stack.sh
│   ├── kustomization.yaml
│   ├── local-monitoring-values.yaml
│   └── secret.yaml
└── eks/
    ├── README.md
    ├── configmap-patch.yaml
    ├── kustomization.yaml
    ├── publish-images.sh
    └── secret.example.yaml
```

## Purpose

The `base` directory contains reusable Kubernetes resources that should be common across environments, such as deployments, services, config maps, namespaces, and ingress definitions.

Each overlay customizes those base resources for a specific environment.

## Local Overlay

The `local` overlay is used for running the system on a local `k3d` cluster. Its deployment helper also installs the local Prometheus, Grafana, and Alertmanager stack.

Deploy the full local stack with:

```bash
bash infra/k8s/overlays/local/deploy-local-stack.sh
```

The `kube-prometheus-stack` Helm release must be installed before applying the overlay directly, because the overlay includes `ServiceMonitor` and `PrometheusRule` custom resources.

## EKS Overlay

The `eks` overlay contains the first minimal AWS EKS-specific configuration.

It reuses the shared base manifests and overrides only environment-specific values such as image references and `APP_ENV`.

### EKS Prerequisite

The EKS overlay intentionally does not include real secrets.

Before applying the overlay, create a Kubernetes `Secret` named `application-secrets` in the `dist-jobs` namespace.

```bash
kubectl create secret generic application-secrets \
    -n dist-jobs \
    --from-literal=POSTGRES_DB=jobs \
    --from-literal=POSTGRES_USER=postgres \
    --from-literal=POSTGRES_PASSWORD=replace-me \
    --from-literal=DATABASE_URL='postgresql+psycopg://postgres:replace-me@postgres:5432/jobs' \
    --from-literal=CELERY_BROKER_URL='amqp://guest:guest@rabbitmq:5672//'
```

Apply with:

```bash
kubectl apply -k infra/k8s/overlays/eks
```

For ECR image publishing and overlay image updates, see [infra/k8s/overlays/eks/README.md](c:/Users/Alex/OneDrive/Documents/GitHub/distributed-job-processing-system/infra/k8s/overlays/eks/README.md).

## Rule Of Thumb

Put shared Kubernetes configuration in `base`.

Put environment-specific differences in the relevant overlay.
