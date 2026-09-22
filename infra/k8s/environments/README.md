# Kubernetes Environment Support

This directory contains environment-specific bootstrap and platform configuration. Application resources are rendered exclusively from the [distributed-jobs Helm chart](../charts/distributed-jobs).

## Local

`local/` contains:

- `deploy-local-stack.sh`, which recreates the k3d environment and installs platform dependencies plus the application Helm release
- `local-monitoring-values.yaml`, which constrains the local Prometheus, Grafana, and Alertmanager installation

Deploy locally with:

```bash
bash infra/k8s/environments/local/deploy-local-stack.sh
```

## EKS

`eks/` contains:

- `deploy-eks-application-stack.sh`, which bootstraps the EKS application platform
- `destroy-eks-application-stack.sh`, which removes the application stack before Terraform destroys AWS infrastructure
- `publish-images.sh`, which builds and publishes immutable ECR images
- EKS monitoring values and deployment documentation

Deploy EKS with:

```bash
bash infra/k8s/environments/eks/deploy-eks-application-stack.sh
```
