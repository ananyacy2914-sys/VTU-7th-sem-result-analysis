FROM python:3.11-slim

# Install Chromium and ChromeDriver (much simpler than Chrome)
RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set Chrome/Chromium binary location for Selenium
ENV CHROME_BIN=/usr/bin/chromium
ENV CHROMEDRIVER_PATH=/usr/bin/chromedriver

# Set working directory
WORKDIR /app

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Expose port
EXPOSE 10000

# Run the application
CMD gunicorn --bind 0.0.0.0:$PORT --timeout 120 --workers 1 run_app:app