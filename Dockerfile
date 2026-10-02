FROM node:22-alpine AS frontend-build
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS backend-base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home pocket
COPY backend/ ./backend/
USER pocket

FROM backend-base AS bot
CMD ["python", "-m", "backend.bot"]

FROM backend-base AS web
ENV STATIC_DIR=/app/static
COPY --from=frontend-build /frontend/dist ./static
EXPOSE 8000
CMD ["uvicorn", "backend.web.main:app", "--host", "0.0.0.0", "--port", "8000"]
