# Cria repositórios no Amazon ECR para armazenar as imagens Docker do chatbot-api.
aws ecr create-repository --repository-name chatbot-api --region sa-east-1

# Mesma coisa, só que pro Redis.
aws ecr create-repository --repository-name chatbot-api --region sa-east-1