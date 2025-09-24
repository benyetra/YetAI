#!/usr/bin/env python3
"""
Script to configure S3 bucket for YetAI avatar storage
Run this once after creating the S3 bucket to set up proper permissions
"""

import boto3
import json
import os
import sys
from botocore.exceptions import ClientError


def setup_s3_bucket():
    """Configure S3 bucket for avatar storage"""

    # Configuration
    bucket_name = "yetai"
    region = "us-east-2"

    print(f"🚀 Setting up S3 bucket: {bucket_name}")

    try:
        # Initialize S3 client
        s3_client = boto3.client(
            's3',
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            region_name=region
        )

        # Test bucket access
        print("✅ Testing bucket access...")
        s3_client.head_bucket(Bucket=bucket_name)
        print("✅ Bucket access confirmed")

        # Configure CORS for web uploads
        print("🔧 Setting up CORS policy...")
        cors_config = {
            'CORSRules': [
                {
                    'AllowedHeaders': ['*'],
                    'AllowedMethods': ['GET', 'PUT', 'POST', 'DELETE', 'HEAD'],
                    'AllowedOrigins': [
                        'https://yetai.app',
                        'https://www.yetai.app',
                        'http://localhost:3000',
                        'http://localhost:8000'
                    ],
                    'ExposeHeaders': ['ETag'],
                    'MaxAgeSeconds': 3000
                }
            ]
        }

        s3_client.put_bucket_cors(Bucket=bucket_name, CORSConfiguration=cors_config)
        print("✅ CORS policy configured")

        # Set public read policy for avatars folder
        print("🔧 Setting up bucket policy for public read access...")
        bucket_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "PublicReadGetObject",
                    "Effect": "Allow",
                    "Principal": "*",
                    "Action": "s3:GetObject",
                    "Resource": f"arn:aws:s3:::{bucket_name}/avatars/*"
                }
            ]
        }

        s3_client.put_bucket_policy(
            Bucket=bucket_name,
            Policy=json.dumps(bucket_policy)
        )
        print("✅ Bucket policy configured for public read access")

        # Configure bucket versioning (optional but recommended)
        print("🔧 Enabling versioning...")
        s3_client.put_bucket_versioning(
            Bucket=bucket_name,
            VersioningConfiguration={
                'Status': 'Enabled'
            }
        )
        print("✅ Versioning enabled")

        # Test upload to avatars folder
        print("🧪 Testing upload to avatars folder...")
        test_key = "avatars/test-setup.txt"
        s3_client.put_object(
            Bucket=bucket_name,
            Key=test_key,
            Body=b"YetAI S3 setup test",
            ContentType="text/plain",
            ACL="public-read"
        )

        # Test public access
        test_url = f"https://{bucket_name}.s3.{region}.amazonaws.com/{test_key}"
        print(f"✅ Test file uploaded: {test_url}")

        # Clean up test file
        s3_client.delete_object(Bucket=bucket_name, Key=test_key)
        print("✅ Test cleanup completed")

        print("\n🎉 S3 bucket setup completed successfully!")
        print(f"\nBucket URL format: https://{bucket_name}.s3.{region}.amazonaws.com/avatars/filename.jpg")
        print("\nEnvironment variables needed:")
        print("AWS_ACCESS_KEY_ID=your_access_key")
        print("AWS_SECRET_ACCESS_KEY=your_secret_key")
        print(f"AWS_REGION={region}")
        print(f"AWS_S3_BUCKET_NAME={bucket_name}")

    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == 'NoSuchBucket':
            print(f"❌ Bucket {bucket_name} does not exist. Please create it first.")
        elif error_code == 'AccessDenied':
            print("❌ Access denied. Check your AWS credentials and permissions.")
        else:
            print(f"❌ AWS Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    setup_s3_bucket()