# Argo CD Configuration

This directory contains resources that configure Argo CD itself. It is separate from `infra/k8s/overlays/local/`, which contains the application resources that Argo CD observes and eventually manages.

## Why this directory is separate

`local-application.yaml` is an Argo CD `Application` resource. It tells Argo CD where desired state is stored and where that state should be deployed; it is not part of the distributed jobs workload.

Keeping the resource outside the managed local overlay creates a clear ownership boundary:

```text
infra/k8s/argocd/          configures Argo CD
infra/k8s/overlays/local/  contains resources managed by Argo CD
```

It also prevents the local Application from including and managing its own definition recursively.

## Install the control plane

The Argo CD control plane is installed by `infra/k8s/overlays/local/deploy-local-stack.sh` with the pinned official Helm chart:

```bash
helm upgrade --install "$ARGOCD_RELEASE" oci://ghcr.io/argoproj/argo-helm/argo-cd \
  --namespace "$ARGOCD_NAMESPACE" \
  --create-namespace \
  --version "$ARGOCD_CHART_VERSION" \
  --atomic \
  --wait \
  --timeout 10m
```

This installs the Argo CD API server, repository server, application controller, and supporting components. Installing the control plane does not assign it any application resources.

## Register the local Application

After Helm reports the control plane ready, the deployment script registers the local Application:

```bash
kubectl apply --filename infra/k8s/argocd/local-application.yaml
```

The Application tracks:

- repository: `https://github.com/programmingwithalex/distributed-job-processing-system.git`
- revision: `main`
- source path: `infra/k8s/overlays/local`
- destination namespace: `dist-jobs`

## Automated synchronization

The Application automatically applies desired state from `main` and corrects live drift:

```yaml
syncPolicy:
  automated:
    enabled: true
    selfHeal: true
    prune: false
```

- `enabled: true` allows Argo CD to synchronize without manual approval
- `selfHeal: true` restores resources when live cluster configuration differs from Git
- `prune: false` prevents automatic deletion when a resource is removed from Git

Keeping pruning disabled separates drift recovery from deletion authority. Resource deletion can be enabled and tested as a later policy change.

Use [SELF_HEALING_VALIDATION.md](SELF_HEALING_VALIDATION.md) for the repeatable local drift and recovery demonstration.

## Destination server

The destination block identifies both a Kubernetes cluster and a namespace inside that cluster:

```yaml
destination:
  server: https://kubernetes.default.svc
  namespace: dist-jobs
```

`server` refers to the destination Kubernetes API server, not the Argo CD web server. Kubernetes automatically provides the internal `kubernetes` Service in the `default` namespace, and cluster DNS expands its name as follows:

```text
kubernetes.default.svc
|          |       |
service    namespace cluster DNS suffix
```

`https://kubernetes.default.svc` therefore means the cluster where Argo CD is running. Combined with `namespace: dist-jobs`, the destination means the `dist-jobs` namespace in the current local k3d cluster.
