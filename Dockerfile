# Use Python 3.8 slim image
FROM python:3.8-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    libopencv-dev \
    python3-opencv \
    adb \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p images macros logs config SQL

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV DISPLAY=:0

# Expose port for X11 forwarding
EXPOSE 6000

# Run the application
CMD ["python", "BCAapp.py"] 