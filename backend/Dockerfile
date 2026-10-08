FROM node:22-slim AS frontend-build
WORKDIR /ui
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
COPY backend/requirements.txt backend/requirements-dev.txt ./
RUN pip install -r requirements-dev.txt
COPY backend/ backend/
COPY data/ data/
COPY scripts/ scripts/
COPY --from=frontend-build /ui/dist/ backend/dashboard/
RUN mkdir -p runtime logs data/uploads
EXPOSE 8099
CMD ["python", "scripts/start_container.py"]
