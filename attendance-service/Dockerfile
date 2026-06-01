FROM python:3.12-slim
WORKDIR /workspace/attendance-service
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/workspace/attendance-service:/workspace/shared/python
COPY requirements /workspace/requirements
COPY attendance-service/requirements.txt /workspace/attendance-service/requirements.txt
RUN pip install --no-cache-dir -r /workspace/attendance-service/requirements.txt
COPY attendance-service /workspace/attendance-service
COPY shared/python /workspace/shared/python
EXPOSE 8001
CMD ["sh", "scripts/start.sh"]
