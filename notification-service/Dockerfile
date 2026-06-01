FROM python:3.12-slim
WORKDIR /workspace/notification-service
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/workspace/notification-service:/workspace/shared/python
COPY requirements /workspace/requirements
COPY notification-service/requirements.txt /workspace/notification-service/requirements.txt
RUN pip install --no-cache-dir -r /workspace/notification-service/requirements.txt
COPY notification-service /workspace/notification-service
COPY shared/python /workspace/shared/python
EXPOSE 8003
CMD ["sh", "scripts/start.sh"]
