# Use Python 3.9 Slim
FROM python:3.9-slim

# 1. Install Chromium and Driver (Stable method)
RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
    wget \
    && rm -rf /var/lib/apt/lists/*

# 2. Set Working Directory
WORKDIR /app

# 3. Copy Requirements and Install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. Copy App Files
COPY . .

# 5. Environment Variables
ENV CHROME_BIN=/usr/bin/chromium
ENV CHROMEDRIVER_PATH=/usr/bin/chromedriver
ENV PORT=10000

# 6. Start Command (Updated to use run_app:app)
CMD ["gunicorn", "run_app:app", "--bind", "0.0.0.0:10000", "--timeout", "120"]