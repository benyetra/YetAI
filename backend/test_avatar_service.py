#!/usr/bin/env python3
"""
Test script for avatar service S3 integration
"""

import sys
import os
import base64
from pathlib import Path

# Add app directory to path
sys.path.insert(0, str(Path(__file__).parent))

from app.services.avatar_service import avatar_service


def create_test_image():
    """Create a simple test image in base64 format"""
    from PIL import Image
    import io

    # Create a simple 100x100 red square
    img = Image.new("RGB", (100, 100), color="red")
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG")
    buffer.seek(0)

    # Convert to base64
    img_data = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return f"data:image/jpeg;base64,{img_data}"


def test_avatar_service():
    """Test the avatar service S3 integration"""
    print("🧪 Testing YetAI Avatar Service...")

    # Check if S3 is configured
    if avatar_service.use_s3:
        print("✅ S3 configuration detected")
        print(f"Bucket: {avatar_service.bucket_name}")
        print(f"Region: {avatar_service.aws_region}")
    else:
        print("⚠️ Using local storage (S3 not configured)")

    # Test with a sample image
    print("\n📸 Creating test image...")
    test_image = create_test_image()

    print("💾 Testing avatar save...")
    success, result = avatar_service.save_avatar(999, test_image)  # Test user ID 999

    if success:
        print("✅ Avatar save successful!")
        if isinstance(result, dict):
            print(f"Avatar URL: {result.get('avatar', 'N/A')}")
            print(f"Thumbnail URL: {result.get('thumbnail', 'N/A')}")
        else:
            print(f"Result: {result}")
    else:
        print(f"❌ Avatar save failed: {result}")
        return False

    # Test avatar URL generation
    print("\n🔗 Testing avatar URL generation...")
    test_user = {"email": "test@yetai.app", "first_name": "Test", "last_name": "User"}

    default_avatar = avatar_service.get_avatar_url(test_user)
    print(f"Default avatar URL: {default_avatar[:100]}...")

    # Test with uploaded avatar
    if isinstance(result, dict) and result.get("avatar"):
        test_user["avatar_url"] = result["avatar"]
        uploaded_avatar = avatar_service.get_avatar_url(test_user)
        print(f"Uploaded avatar URL: {uploaded_avatar}")

    print("\n✅ Avatar service test completed!")
    return True


if __name__ == "__main__":
    try:
        test_avatar_service()
    except Exception as e:
        print(f"❌ Test failed: {e}")
        sys.exit(1)
