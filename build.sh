#!/usr/bin/env bash
set -o errexit

cd $HOME/project/src

# Install Python dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Download Chromium for Pyppeteer
echo "Downloading Chromium..."
python -c "import pyppeteer; pyppeteer.chromium_downloader.download_chromium()"

echo "✅ Build completed successfully!"