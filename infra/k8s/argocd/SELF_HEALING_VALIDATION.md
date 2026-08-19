# Validate Argo CD Self-Healing

Use separate WSL or Bash terminals so the Argo CD UI, Application state, and API Deployment remain visible while introducing drift.

## Open the Argo CD UI

In terminal 1, forward the Argo CD server and open <https://localhost:8081>:

```bash
kubectl port-forward --namespace argocd service/argocd-server 8081:443
```

Select the `dist-jobs-local` Application in the UI.

## Watch the Application

In terminal 2, watch the Application synchronization and health state:

```bash
kubectl get application dist-jobs-local \
  --namespace argocd \
  --watch
```

## Watch the API Deployment

In terminal 3, watch the API Deployment replica state:

```bash
kubectl get deployment api \
  --namespace dist-jobs \
  --watch
```

## Apply and verify the policy

In terminal 4, apply the Application policy and verify its values:

```bash
kubectl apply --filename infra/k8s/argocd/local-application.yaml

kubectl get application dist-jobs-local \
  --namespace argocd \
  --output jsonpath='enabled={.spec.syncPolicy.automated.enabled}, selfHeal={.spec.syncPolicy.automated.selfHeal}, prune={.spec.syncPolicy.automated.prune}{"\n"}'
```

Expected policy:

```text
enabled=true, selfHeal=true, prune=false
```

## Introduce drift

Change the live API replica count from the Git-declared value of two to one:

```bash
kubectl scale deployment/api --namespace dist-jobs --replicas=1
```

Argo CD should detect the drift and restore two replicas without a manual sync.

## Verify recovery

Confirm the restored Deployment, Application state, and API health:

```bash
kubectl wait deployment/api \
  --namespace dist-jobs \
  --for=jsonpath='{.spec.replicas}'=2 \
  --timeout=120s

kubectl rollout status deployment/api \
  --namespace dist-jobs \
  --timeout=120s

kubectl get application dist-jobs-local --namespace argocd
curl --fail http://localhost:8080/api/health
```

The final Application state should be `Synced / Healthy`, and the health endpoint should return `{"status":"ok"}`.
