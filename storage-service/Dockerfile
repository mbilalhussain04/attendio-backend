FROM python:3.12-slim
WORKDIR /workspace/storage-service
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/workspace/storage-service:/workspace/shared/python
COPY requirements /workspace/requirements
COPY storage-service/requirements.txt /workspace/storage-service/requirements.txt
RUN pip install --no-cache-dir -r /workspace/storage-service/requirements.txt
COPY storage-service /workspace/storage-service
COPY shared/python /workspace/shared/python
EXPOSE 8002
CMD ["sh", "scripts/start.sh"]
