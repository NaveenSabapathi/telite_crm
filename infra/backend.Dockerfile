FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv
COPY backend/requirements.lock /srv/backend/requirements.lock
RUN pip install --no-cache-dir -r /srv/backend/requirements.lock && useradd --create-home --uid 10001 crm
COPY backend /srv/backend
COPY db /srv/db
USER crm
WORKDIR /srv/backend
EXPOSE 8000
CMD ["uvicorn","app.api:app","--host","0.0.0.0","--port","8000","--proxy-headers","--forwarded-allow-ips=*"]
