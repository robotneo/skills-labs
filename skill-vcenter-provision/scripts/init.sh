#!/bin/bash

echo "🔧 Initializing Python package structure..."

# 自动创建 __init__.py
find scripts -type d -exec touch {}/__init__.py \;

echo "✅ Done."