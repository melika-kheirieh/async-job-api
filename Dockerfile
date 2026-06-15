FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .

ARG PIP_INDEX_URL=https://package-mirror.liara.ir/repository/pypi/simple
ARG PIP_EXTRA_INDEX_URL=https://pypi.org/simple
ARG PIP_RETRIES=10
ARG PIP_TIMEOUT=120

RUN python -m pip install --no-cache-dir \
    --prefer-binary \
    --retries "$PIP_RETRIES" \
    --timeout "$PIP_TIMEOUT" \
    --index-url "$PIP_INDEX_URL" \
    --extra-index-url "$PIP_EXTRA_INDEX_URL" \
    -r requirements.txt

COPY app ./app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
