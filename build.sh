#!/usr/bin/env bash
set -o errexit

cd $HOME/project/src

# Install Python dependencies
pip install --upgrade pip
pip install -r requirements.txt

echo "✅ Build completed successfully!"