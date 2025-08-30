# Use Python base image
FROM python:3.11-slim

# Install system dependencies for pyzbar + opencv
RUN apt-get update && apt-get install -y \
    libzbar0 \
    libgl1 \
    libglib2.0-0 \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Set work directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Collect static files
RUN python manage.py collectstatic --noinput

# Run migrations then start gunicorn
CMD python manage.py migrate --noinput && \
    gunicorn projecto_engen.wsgi:application --bind 0.0.0.0:$PORT
