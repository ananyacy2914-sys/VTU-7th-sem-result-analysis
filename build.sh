#!/usr/bin/env bash
set -o errexit

cd $HOME/project/src

# Install Python dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium
playwright install-deps chromium

echo "✅ Build completed successfully!"