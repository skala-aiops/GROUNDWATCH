FROM node:22-slim AS frontend-build
WORKDIR /ui
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
COPY requirements.txt requirements-dev.txt ./
RUN pip install -r requirements-dev.txt
COPY serving_app/ serving_app/
COPY data/ data/
COPY scripts/ scripts/
COPY tests/ tests/
COPY --from=frontend-build /ui/dist/ serving_app/dashboard/
RUN mkdir -p runtime logs data/uploads
EXPOSE 8099
CMD ["python", "scripts/start_container.py"]
