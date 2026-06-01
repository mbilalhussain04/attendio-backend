FROM python:3.12-slim
WORKDIR /workspace/auth-service
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/workspace/auth-service:/workspace/shared/python
RUN apt-get update && apt-get install -y --no-install-recommends build-essential curl && rm -rf /var/lib/apt/lists/*
COPY requirements /workspace/requirements
COPY auth-service/requirements.txt /workspace/auth-service/requirements.txt
RUN pip install --no-cache-dir -r /workspace/auth-service/requirements.txt
COPY auth-service /workspace/auth-service
COPY shared/python /workspace/shared/python
CMD ["sh", "scripts/start.sh"]
