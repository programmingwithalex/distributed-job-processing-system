# EKS Image Publishing

Before applying the EKS overlay, publish the three application images to Amazon ECR.

Quick start:

```bash
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

bash infra/k8s/overlays/eks/publish-images.sh "$AWS_ACCOUNT_ID" us-east-1 v1
```

Will also update `.\kustomization.yaml` with ECR images after pushed.

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
bash infra/k8s/overlays/eks/publish-images.sh <aws_account_id> us-east-1 v1
```

The script will:

- create the `distributed-job-processing-system-api` ECR repository if missing
- create the `distributed-job-processing-system-celery-worker` ECR repository if missing
- create the `distributed-job-processing-system-frontend` ECR repository if missing
- authenticate Docker to ECR
- build the `api`, `celery_worker`, and `frontend` images with Docker Compose
- tag and push those images to ECR
- update [kustomization.yaml](c:/Users/Alex/OneDrive/Documents/GitHub/distributed-job-processing-system/infra/k8s/overlays/eks/kustomization.yaml) with the ECR image URLs and tag

## Equivalent Manual Commands

```bash
AWS_ACCOUNT_ID=123456789012
AWS_REGION=us-east-1
IMAGE_TAG=v1
ECR_REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

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
