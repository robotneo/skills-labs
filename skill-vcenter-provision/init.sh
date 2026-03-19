#!/bin/bash

echo "🔧 Initializing Python package structure..."

# 自动创建 __init__.py，排除隐藏目录和 __pycache__
find scripts -type d \( -name ".*" -o -name "__pycache__" \) -prune -o -type d -exec touch {}/__init__.py \;
find assets -type d \( -name ".*" -o -name "__pycache__" \) -prune -o -type d -exec touch {}/__init__.py \;

echo "✅ Done."