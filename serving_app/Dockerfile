FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY serving_app/ serving_app/
COPY data/ data/
COPY scripts/ scripts/
COPY tests/ tests/
RUN mkdir -p runtime logs data/uploads
EXPOSE 8099
CMD ["python", "scripts/start_container.py"]
