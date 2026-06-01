# GitHub Secrets Required

Configure these secrets in your GitHub repository under **Settings → Secrets and variables → Actions**.

## CI Pipeline (ci.yml)

| Secret Name | Description | Example |
|-------------|-------------|---------|
| `DOCKERHUB_USERNAME` | Docker Hub username | `johnbaabalola` |
| `DOCKERHUB_TOKEN` | Docker Hub access token (not password) | `dckr_pat_...` |

## CD Pipeline (cd.yml)

| Secret Name | Description | Example |
|-------------|-------------|---------|
| `AWS_ACCESS_KEY_ID` | IAM user access key for EKS deploy | `AKIA...` |
| `AWS_SECRET_ACCESS_KEY` | IAM user secret key | `wJal...` |
| `AWS_REGION` | AWS region | `eu-west-2` |
| `EKS_CLUSTER_NAME` | EKS cluster name | `vidcast-cluster` |
| `DOCKERHUB_USERNAME` | Same as above — used to set image name | `johnbaabalola` |

## Jenkins Pipeline (Jenkinsfile)

Configure these in Jenkins under **Manage Jenkins → Credentials**.

| Credential ID | Type | Description |
|---------------|------|-------------|
| `dockerhub-credentials` | Username/Password | Docker Hub login |
| `aws-credentials` | AWS Credentials | IAM key for EKS access |
| `swarm-staging-ip` | Secret text | IP address of Swarm staging EC2 |

## How to Create a Docker Hub Access Token

1. Log in to hub.docker.com
2. Account Settings → Security → New Access Token
3. Name it `github-actions-vidcast`
4. Copy the token immediately — it won't be shown again
5. Add as `DOCKERHUB_TOKEN` in GitHub Secrets

## How to Create the AWS IAM User for CI/CD

```bash
aws iam create-user --user-name vidcast-cicd
aws iam attach-user-policy --user-name vidcast-cicd \
  --policy-arn arn:aws:iam::aws:policy/AmazonEKSClusterPolicy
# For minimal permissions, use a custom policy allowing only:
# eks:UpdateClusterVersion, eks:DescribeCluster, and kubectl via kubeconfig
aws iam create-access-key --user-name vidcast-cicd
```
