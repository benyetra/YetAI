#!/bin/bash
# Install S3 dependencies for avatar storage

echo "🚀 Installing S3 dependencies for YetAI avatar storage..."

# Install boto3
pip install boto3==1.34.162

echo "✅ boto3 installed successfully"

# Verify installation
python -c "import boto3; print(f'✅ boto3 version: {boto3.__version__}')"

echo ""
echo "📋 Environment variables needed:"
echo "AWS_ACCESS_KEY_ID=your_access_key"
echo "AWS_SECRET_ACCESS_KEY=your_secret_key"
echo "AWS_REGION=us-east-2"
echo "AWS_S3_BUCKET_NAME=yetai"
echo ""
echo "🔧 To configure S3 bucket permissions, run:"
echo "cd backend && python scripts/setup_s3_bucket.py"
echo ""
echo "✅ S3 dependencies installation complete!"