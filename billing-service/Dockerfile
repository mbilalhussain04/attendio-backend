FROM python:3.12-slim
WORKDIR /workspace/billing-service
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/workspace/billing-service:/workspace/shared/python
COPY billing-service/requirements.txt /workspace/billing-service/requirements.txt
RUN pip install --no-cache-dir -r /workspace/billing-service/requirements.txt
COPY billing-service /workspace/billing-service
COPY shared/python /workspace/shared/python
EXPOSE 8005
CMD ["sh", "scripts/start.sh"]
