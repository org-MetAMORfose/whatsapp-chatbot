# Simula o que o GitHub Actions vai fazer.
aws sts get-caller-identity

# Testa acesso ao ECR.
aws ecr describe-repositories --region sa-east-1

# Testa acesso ao ECS.
aws ecs describe-clusters --region sa-east-1