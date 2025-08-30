# Use official Python image
FROM python:3.13-slim

# Prevent Python from writing .pyc files
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install system dependencies (zbar + build tools)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libzbar0 gcc g++ \
    && rm -rf /var/lib/apt/lists/*

# Set workdir
WORKDIR /app

# Copy dependency files first
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy rest of the project
COPY . .

# Collect static files at build time (optional)
RUN python manage.py collectstatic --noinput

# Run migrations at runtime (entrypoint or CMD)
CMD ["gunicorn", "projecto_engen.wsgi:application", "--bind", "0.0.0.0:8000"]
