FROM python:3.12-slim
WORKDIR /workspace/docs-gateway
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/workspace/docs-gateway:/workspace/shared/python
COPY requirements /workspace/requirements
COPY docs-gateway/requirements.txt /workspace/docs-gateway/requirements.txt
RUN pip install --no-cache-dir -r /workspace/docs-gateway/requirements.txt
COPY docs-gateway /workspace/docs-gateway
COPY shared/python /workspace/shared/python
EXPOSE 8090
CMD ["uvicorn", "docs_gateway.main:app", "--host", "0.0.0.0", "--port", "8090"]
