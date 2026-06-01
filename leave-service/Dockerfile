FROM python:3.12-slim
WORKDIR /workspace/leave-service
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/workspace/leave-service:/workspace/shared/python
COPY requirements /workspace/requirements
COPY leave-service/requirements.txt /workspace/leave-service/requirements.txt
RUN pip install --no-cache-dir -r /workspace/leave-service/requirements.txt
COPY leave-service /workspace/leave-service
COPY shared/python /workspace/shared/python
EXPOSE 8004
CMD ["sh", "scripts/start.sh"]
