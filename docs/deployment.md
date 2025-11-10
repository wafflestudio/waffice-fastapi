# Deployment Guide

This guide covers deploying the Waffice FastAPI application to AWS using ECR (Elastic Container Registry) and various compute services.

## Prerequisites

- AWS Account with appropriate permissions
- AWS CLI installed and configured
- Docker installed locally (for testing)
- GitHub repository with Actions enabled

## 1. AWS ECR Setup

### Create ECR Repository

```bash
# Set your AWS region
export AWS_REGION=ap-northeast-2  # or your preferred region

# Create ECR repository
aws ecr create-repository \
    --repository-name waffice-fastapi \
    --region $AWS_REGION \
    --image-scanning-configuration scanOnPush=true \
    --encryption-configuration encryptionType=AES256

# Note the repositoryUri from the output
```

### Get Repository URI

```bash
# Get your ECR repository URI
aws ecr describe-repositories \
    --repository-names waffice-fastapi \
    --region $AWS_REGION \
    --query 'repositories[0].repositoryUri' \
    --output text
```

The output will look like: `123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/waffice-fastapi`

## 2. GitHub Secrets Configuration

Add the following secrets to your GitHub repository:

**Settings → Secrets and variables → Actions → New repository secret**

| Secret Name | Description | Example Value |
|-------------|-------------|---------------|
| `AWS_ACCESS_KEY_ID` | AWS access key for ECR push | `AKIAIOSFODNN7EXAMPLE` |
| `AWS_SECRET_ACCESS_KEY` | AWS secret access key | `wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY` |
| `AWS_REGION` | AWS region for ECR | `ap-northeast-2` |
| `ECR_REPOSITORY` | ECR repository name (not URI) | `waffice-fastapi` |

### Creating AWS IAM User for GitHub Actions

```bash
# Create IAM policy for ECR access
cat > ecr-push-policy.json << EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ecr:GetAuthorizationToken",
        "ecr:BatchCheckLayerAvailability",
        "ecr:GetDownloadUrlForLayer",
        "ecr:PutImage",
        "ecr:InitiateLayerUpload",
        "ecr:UploadLayerPart",
        "ecr:CompleteLayerUpload"
      ],
      "Resource": "*"
    }
  ]
}
EOF

# Create IAM user for GitHub Actions
aws iam create-user --user-name github-actions-ecr-push

# Create and attach policy
aws iam create-policy \
    --policy-name ECRPushPolicy \
    --policy-document file://ecr-push-policy.json

# Attach policy to user (replace ACCOUNT_ID with your AWS account ID)
aws iam attach-user-policy \
    --user-name github-actions-ecr-push \
    --policy-arn arn:aws:iam::ACCOUNT_ID:policy/ECRPushPolicy

# Create access keys
aws iam create-access-key --user-name github-actions-ecr-push
```

## 3. Local Testing

### Build the Docker Image

```bash
# Build for arm64
docker build --platform linux/arm64 -t waffice-fastapi:latest .

# Or build for your local architecture (for testing)
docker build -t waffice-fastapi:latest .
```

### Run Locally

```bash
# Start MySQL database first
docker compose up -d db

# Run the FastAPI container
docker run -d \
  --name waffice-api \
  -p 8000:8000 \
  -e DB_HOST=host.docker.internal \
  -e DB_PORT=3306 \
  -e DB_USER=myuser \
  -e DB_PASSWORD=mypass \
  -e DB_NAME=mydb \
  waffice-fastapi:latest

# Check logs
docker logs -f waffice-api

# Access the API
curl http://localhost:8000/docs
```

### Test with Docker Compose

Alternatively, use the updated `docker-compose.yml` to run both services:

```bash
docker compose up -d
```

Access at http://localhost:8000/docs

### Push Manually to ECR (Optional)

```bash
# Login to ECR
aws ecr get-login-password --region $AWS_REGION | \
    docker login --username AWS --password-stdin \
    123456789012.dkr.ecr.$AWS_REGION.amazonaws.com

# Tag the image
docker tag waffice-fastapi:latest \
    123456789012.dkr.ecr.$AWS_REGION.amazonaws.com/waffice-fastapi:latest

# Push to ECR
docker push 123456789012.dkr.ecr.$AWS_REGION.amazonaws.com/waffice-fastapi:latest
```

## 4. Automated Deployment

### GitHub Actions Workflow

The `.github/workflows/deploy-ecr.yaml` workflow automatically:

1. Triggers on every push to `main` branch
2. Builds arm64 Docker image
3. Pushes to ECR with three tags:
   - `latest` - always points to the most recent build
   - `<commit-sha>` - immutable reference to specific commit
   - `<timestamp>` - build timestamp for tracking

### Monitoring Deployments

Check workflow status:
- GitHub → Actions tab
- View logs for each deployment
- Verify ECR images in AWS Console

## 5. Deploying to AWS Services

### Option A: AWS ECS (Elastic Container Service) - Recommended

#### Using AWS Fargate (Serverless)

```bash
# Create ECS cluster
aws ecs create-cluster \
    --cluster-name waffice-cluster \
    --region $AWS_REGION

# Create task definition (save as task-definition.json)
# See example task definition below

# Register task definition
aws ecs register-task-definition \
    --cli-input-json file://task-definition.json

# Create ECS service
aws ecs create-service \
    --cluster waffice-cluster \
    --service-name waffice-api-service \
    --task-definition waffice-fastapi:1 \
    --desired-count 1 \
    --launch-type FARGATE \
    --network-configuration "awsvpcConfiguration={subnets=[subnet-xxxxx],securityGroups=[sg-xxxxx],assignPublicIp=ENABLED}"
```

#### Example ECS Task Definition

```json
{
  "family": "waffice-fastapi",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "256",
  "memory": "512",
  "runtimePlatform": {
    "cpuArchitecture": "ARM64",
    "operatingSystemFamily": "LINUX"
  },
  "containerDefinitions": [
    {
      "name": "waffice-api",
      "image": "123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/waffice-fastapi:latest",
      "portMappings": [
        {
          "containerPort": 8000,
          "protocol": "tcp"
        }
      ],
      "environment": [
        {"name": "DB_HOST", "value": "your-rds-endpoint.rds.amazonaws.com"},
        {"name": "DB_PORT", "value": "3306"},
        {"name": "DB_NAME", "value": "mydb"}
      ],
      "secrets": [
        {"name": "DB_USER", "valueFrom": "arn:aws:secretsmanager:region:account:secret:db-user"},
        {"name": "DB_PASSWORD", "valueFrom": "arn:aws:secretsmanager:region:account:secret:db-password"}
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/waffice-fastapi",
          "awslogs-region": "ap-northeast-2",
          "awslogs-stream-prefix": "ecs"
        }
      }
    }
  ]
}
```

### Option B: AWS EC2 (Graviton Instances)

```bash
# Launch EC2 instance (Graviton ARM64)
aws ec2 run-instances \
    --image-id ami-xxxxx \
    --instance-type t4g.micro \
    --key-name your-key-pair \
    --security-group-ids sg-xxxxx \
    --subnet-id subnet-xxxxx

# SSH into the instance
ssh -i your-key.pem ec2-user@instance-public-ip

# Install Docker
sudo yum update -y
sudo yum install docker -y
sudo service docker start
sudo usermod -a -G docker ec2-user

# Login to ECR
aws ecr get-login-password --region ap-northeast-2 | \
    docker login --username AWS --password-stdin \
    123456789012.dkr.ecr.ap-northeast-2.amazonaws.com

# Pull and run the container
docker pull 123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/waffice-fastapi:latest

docker run -d \
  --name waffice-api \
  -p 8000:8000 \
  --restart unless-stopped \
  -e DB_HOST=your-rds-endpoint.rds.amazonaws.com \
  -e DB_PORT=3306 \
  -e DB_USER=myuser \
  -e DB_PASSWORD=mypass \
  -e DB_NAME=mydb \
  123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/waffice-fastapi:latest
```

### Option C: AWS App Runner

```bash
# Create App Runner service
aws apprunner create-service \
    --service-name waffice-api \
    --source-configuration '{
      "ImageRepository": {
        "ImageIdentifier": "123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/waffice-fastapi:latest",
        "ImageRepositoryType": "ECR",
        "ImageConfiguration": {
          "Port": "8000",
          "RuntimeEnvironmentVariables": {
            "DB_HOST": "your-rds-endpoint.rds.amazonaws.com",
            "DB_PORT": "3306",
            "DB_NAME": "mydb"
          }
        }
      },
      "AutoDeploymentsEnabled": true
    }' \
    --instance-configuration '{
      "Cpu": "1 vCPU",
      "Memory": "2 GB"
    }'
```

## 6. Database Setup

### Running Database Migrations

Migrations are NOT run automatically on container startup. Run them manually:

```bash
# If using ECS
aws ecs run-task \
    --cluster waffice-cluster \
    --task-definition waffice-fastapi:1 \
    --overrides '{
      "containerOverrides": [{
        "name": "waffice-api",
        "command": ["uv", "run", "alembic", "upgrade", "head"]
      }]
    }'

# If using EC2, SSH into the instance and run:
docker exec waffice-api uv run alembic upgrade head
```

### Using AWS RDS for MySQL

```bash
# Create RDS MySQL instance (Graviton-compatible)
aws rds create-db-instance \
    --db-instance-identifier waffice-db \
    --db-instance-class db.t4g.micro \
    --engine mysql \
    --engine-version 8.0.35 \
    --master-username admin \
    --master-user-password your-secure-password \
    --allocated-storage 20 \
    --vpc-security-group-ids sg-xxxxx \
    --db-subnet-group-name your-subnet-group
```

## 7. Monitoring and Logging

### CloudWatch Logs

```bash
# Create log group
aws logs create-log-group --log-group-name /ecs/waffice-fastapi

# View logs
aws logs tail /ecs/waffice-fastapi --follow
```

### Container Health Checks

The Dockerfile includes a health check that polls `/docs` endpoint every 30 seconds.

## 8. Troubleshooting

### Image Build Fails

```bash
# Check Docker Buildx
docker buildx ls

# Verify platform support
docker buildx inspect --bootstrap
```

### ECR Push Fails

```bash
# Verify AWS credentials
aws sts get-caller-identity

# Check ECR login
aws ecr get-login-password --region $AWS_REGION

# Verify repository exists
aws ecr describe-repositories --repository-names waffice-fastapi
```

### Container Won't Start

```bash
# Check container logs
docker logs <container-id>

# Test database connectivity
docker run --rm -it waffice-fastapi:latest \
    sh -c "apt-get update && apt-get install -y mysql-client && \
    mysql -h $DB_HOST -u $DB_USER -p$DB_PASSWORD $DB_NAME"
```

### GitHub Actions Workflow Fails

- Verify all secrets are set correctly
- Check AWS IAM permissions
- Review workflow logs in GitHub Actions tab

## 9. Security Best Practices

1. **Use AWS Secrets Manager** for sensitive environment variables
2. **Enable ECR image scanning** for vulnerability detection
3. **Use VPC endpoints** for ECR to avoid public internet traffic
4. **Rotate AWS access keys** regularly
5. **Use least-privilege IAM policies**
6. **Enable CloudTrail** for audit logging
7. **Use HTTPS/TLS** for all external traffic

## 10. Cost Optimization

1. **Use Graviton instances** (t4g family) - up to 40% better price-performance
2. **Enable ECS Fargate Spot** for non-production workloads
3. **Use ECR lifecycle policies** to remove old images
4. **Right-size containers** - start small (256 CPU, 512 MB)
5. **Enable auto-scaling** based on metrics

## Resources

- [AWS ECR Documentation](https://docs.aws.amazon.com/ecr/)
- [AWS ECS Documentation](https://docs.aws.amazon.com/ecs/)
- [Docker Multi-platform Builds](https://docs.docker.com/build/building/multi-platform/)
- [GitHub Actions for AWS](https://github.com/aws-actions)
