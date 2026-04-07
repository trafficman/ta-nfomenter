FROM python:3.11-slim

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /ta-nfomenter-dev

# Install dependencies first to leverage Docker cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

EXPOSE 2960

# Run with Gunicorn for production: 4 workers, 0 timeout due to long running disk I/O tasks, binding to all interfaces on port 2960
CMD ["gunicorn", "--workers", "4", "--bind", "0.0.0.0:2960", "--timeout", "0", "run:app"]
