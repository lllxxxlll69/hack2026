FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend backend
COPY web web
COPY data/case/rules.md data/case/rules.md
COPY data/case/results.schema.json data/case/results.schema.json
RUN useradd --create-home dean && mkdir /app/runtime && chown dean:dean /app/runtime
USER dean
EXPOSE 8000
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
