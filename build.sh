#!/usr/bin/env bash
set -o errexit

cd $HOME/project/src

# Install Python dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Install Playwright and its dependencies
echo "Installing Playwright browsers..."
python -m playwright install chromium

echo "Installing Playwright system dependencies..."
python -m playwright install-deps chromium

echo "✅ Build completed successfully!"