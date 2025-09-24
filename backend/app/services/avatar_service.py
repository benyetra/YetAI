# app/services/avatar_service.py
"""Avatar service for handling user profile pictures"""

import os
import hashlib
import logging
import time
from pathlib import Path
from typing import Optional, Tuple
import base64
from PIL import Image
import io
import secrets
from app.core.config import settings

# Try to import boto3 for S3 support, fallback to local storage
try:
    import boto3
    from botocore.exceptions import ClientError, NoCredentialsError

    HAS_S3 = True
except ImportError:
    HAS_S3 = False

logger = logging.getLogger(__name__)


class AvatarService:
    """Handle user avatar/profile picture operations"""

    def __init__(self):
        # Avatar settings
        self.max_size = (400, 400)  # Maximum dimensions
        self.thumbnail_size = (100, 100)  # Thumbnail dimensions
        self.allowed_formats = {"PNG", "JPEG", "JPG", "GIF", "WEBP"}
        self.max_file_size = 5 * 1024 * 1024  # 5MB

        # Default avatars (generated based on initials)
        self.default_colors = [
            "#A855F7",  # Purple
            "#F59E0B",  # Orange
            "#3B82F6",  # Blue
            "#10B981",  # Green
            "#EF4444",  # Red
            "#8B5CF6",  # Violet
            "#EC4899",  # Pink
            "#14B8A6",  # Teal
        ]

        # Storage configuration
        self.use_s3 = HAS_S3 and self._has_s3_config()

        if self.use_s3:
            self._init_s3()
            logger.info("Using S3 for avatar storage")
        else:
            # Fallback to local storage
            self.base_path = Path(__file__).parent.parent / "uploads" / "avatars"
            self.base_path.mkdir(parents=True, exist_ok=True)
            logger.warning(
                "Using local storage for avatars (files will be lost on deployment)"
            )

    def _has_s3_config(self) -> bool:
        """Check if S3 configuration is available"""
        bucket_name = os.getenv("AWS_S3_BUCKET_NAME", "")
        # Clean up bucket name if it contains s3:// prefix or /avatars suffix
        if bucket_name.startswith("s3://"):
            bucket_name = bucket_name.replace("s3://", "").split("/")[0]

        return bool(
            os.getenv("AWS_ACCESS_KEY_ID")
            and os.getenv("AWS_SECRET_ACCESS_KEY")
            and bucket_name
        )

    def _init_s3(self):
        """Initialize S3 client"""
        try:
            # Get region from either AWS_REGION or AWS_DEFAULT_REGION
            region = os.getenv("AWS_REGION") or os.getenv(
                "AWS_DEFAULT_REGION", "us-east-1"
            )

            self.s3_client = boto3.client(
                "s3",
                aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
                aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
                region_name=region,
            )

            # Clean up bucket name - remove s3:// prefix and /avatars suffix if present
            raw_bucket_name = os.getenv("AWS_S3_BUCKET_NAME", "")
            if raw_bucket_name.startswith("s3://"):
                self.bucket_name = raw_bucket_name.replace("s3://", "").split("/")[0]
            else:
                self.bucket_name = raw_bucket_name.split("/")[
                    0
                ]  # Remove any path suffixes

            self.cloudfront_domain = os.getenv("AWS_CLOUDFRONT_DOMAIN")  # Optional CDN
            self.aws_region = region

            logger.info(
                f"S3 initialized with bucket: {self.bucket_name} in region: {region}"
            )

            # Test S3 connection
            try:
                self.s3_client.head_bucket(Bucket=self.bucket_name)
                logger.info("✅ S3 bucket access confirmed")
            except Exception as e:
                logger.warning(f"⚠️ Cannot access S3 bucket {self.bucket_name}: {e}")

        except Exception as e:
            logger.error(f"Failed to initialize S3: {e}")
            self.use_s3 = False

    def generate_default_avatar(self, email: str, name: Optional[str] = None) -> str:
        """Generate a default avatar SVG based on user initials"""
        # Get initials
        if name and name.strip():
            parts = name.strip().split()
            if len(parts) >= 2:
                initials = f"{parts[0][0]}{parts[-1][0]}".upper()
            else:
                initials = parts[0][:2].upper()
        else:
            initials = email[:2].upper()

        # Generate color based on email hash
        email_hash = hashlib.md5(email.encode(), usedforsecurity=False).hexdigest()
        color_index = int(email_hash[:2], 16) % len(self.default_colors)
        bg_color = self.default_colors[color_index]

        # Create SVG
        svg = f"""
        <svg width="100" height="100" xmlns="http://www.w3.org/2000/svg">
            <rect width="100" height="100" fill="{bg_color}" rx="50"/>
            <text x="50" y="50" font-family="Arial, sans-serif" font-size="36" 
                  fill="white" text-anchor="middle" dominant-baseline="central">
                {initials}
            </text>
        </svg>
        """

        # Convert to base64 data URL
        svg_bytes = svg.strip().encode("utf-8")
        base64_svg = base64.b64encode(svg_bytes).decode("utf-8")
        return f"data:image/svg+xml;base64,{base64_svg}"

    def save_avatar(self, user_id: int, image_data: str) -> Tuple[bool, str]:
        """Save user avatar from base64 data or file upload"""
        try:
            # Parse data URL or base64 string
            if image_data.startswith("data:"):
                # Extract base64 data from data URL
                header, data = image_data.split(",", 1)
                image_bytes = base64.b64decode(data)
            else:
                # Assume it's raw base64
                image_bytes = base64.b64decode(image_data)

            # Check file size
            if len(image_bytes) > self.max_file_size:
                return False, "Image file too large (max 5MB)"

            # Open and validate image
            try:
                img = Image.open(io.BytesIO(image_bytes))

                # Check format
                if img.format not in self.allowed_formats:
                    return (
                        False,
                        f"Invalid image format. Allowed: {', '.join(self.allowed_formats)}",
                    )

                # Convert RGBA to RGB if necessary (for JPEG compatibility)
                if img.mode in ("RGBA", "LA", "P"):
                    # Create a white background
                    background = Image.new("RGB", img.size, (255, 255, 255))
                    if img.mode == "P":
                        img = img.convert("RGBA")
                    background.paste(
                        img, mask=img.split()[-1] if img.mode == "RGBA" else None
                    )
                    img = background

                # Resize image to max dimensions while maintaining aspect ratio
                img.thumbnail(self.max_size, Image.Resampling.LANCZOS)

                # Generate filename
                filename = f"{user_id}_{secrets.token_hex(8)}.jpg"

                if self.use_s3:
                    return self._save_to_s3(img, user_id, filename)
                else:
                    return self._save_to_local(img, filename)

            except Exception as e:
                logger.error(f"Error processing image: {e}")
                return False, "Invalid image file"

        except Exception as e:
            logger.error(f"Error saving avatar: {e}")
            return False, "Failed to save avatar"

    def _save_to_s3(
        self, img: Image.Image, user_id: int, filename: str
    ) -> Tuple[bool, str]:
        """Save avatar to S3"""
        try:
            # Save main image to buffer
            main_buffer = io.BytesIO()
            img.save(main_buffer, "JPEG", quality=85, optimize=True)
            main_buffer.seek(0)

            # Create and save thumbnail to buffer
            thumb = img.copy()
            thumb.thumbnail(self.thumbnail_size, Image.Resampling.LANCZOS)
            thumb_buffer = io.BytesIO()
            thumb.save(thumb_buffer, "JPEG", quality=85, optimize=True)
            thumb_buffer.seek(0)

            # Generate S3 keys
            s3_key = f"avatars/{filename}"
            thumb_filename = f"{user_id}_thumb_{secrets.token_hex(8)}.jpg"
            thumb_s3_key = f"avatars/{thumb_filename}"

            # Upload main image to S3
            logger.info(f"Uploading avatar to S3: {s3_key}")
            self.s3_client.upload_fileobj(
                main_buffer,
                self.bucket_name,
                s3_key,
                ExtraArgs={
                    "ContentType": "image/jpeg",
                    "ACL": "public-read",  # Make publicly accessible
                    "CacheControl": "max-age=31536000",  # 1 year cache
                    "Metadata": {
                        "user-id": str(user_id),
                        "upload-time": str(int(time.time())),
                    },
                },
            )

            # Upload thumbnail to S3
            logger.info(f"Uploading thumbnail to S3: {thumb_s3_key}")
            self.s3_client.upload_fileobj(
                thumb_buffer,
                self.bucket_name,
                thumb_s3_key,
                ExtraArgs={
                    "ContentType": "image/jpeg",
                    "ACL": "public-read",
                    "CacheControl": "max-age=31536000",
                    "Metadata": {
                        "user-id": str(user_id),
                        "upload-time": str(int(time.time())),
                        "type": "thumbnail",
                    },
                },
            )

            # Generate URLs
            if self.cloudfront_domain:
                avatar_url = f"https://{self.cloudfront_domain}/{s3_key}"
                thumb_url = f"https://{self.cloudfront_domain}/{thumb_s3_key}"
            else:
                # Use region-specific S3 URL format
                if self.aws_region == "us-east-1":
                    avatar_url = f"https://{self.bucket_name}.s3.amazonaws.com/{s3_key}"
                    thumb_url = (
                        f"https://{self.bucket_name}.s3.amazonaws.com/{thumb_s3_key}"
                    )
                else:
                    avatar_url = f"https://{self.bucket_name}.s3.{self.aws_region}.amazonaws.com/{s3_key}"
                    thumb_url = f"https://{self.bucket_name}.s3.{self.aws_region}.amazonaws.com/{thumb_s3_key}"

            logger.info(f"✅ Successfully uploaded avatar for user {user_id}")
            logger.info(f"Avatar URL: {avatar_url}")
            logger.info(f"Thumbnail URL: {thumb_url}")

            return True, {
                "avatar": avatar_url,
                "thumbnail": thumb_url,
            }

        except Exception as e:
            logger.error(f"Error saving to S3: {e}")
            return False, f"Failed to save to S3: {str(e)}"

    def _save_to_local(self, img: Image.Image, filename: str) -> Tuple[bool, str]:
        """Save avatar to local filesystem (fallback)"""
        try:
            filepath = self.base_path / filename

            # Save main image
            img.save(filepath, "JPEG", quality=85, optimize=True)

            # Create and save thumbnail
            thumb = img.copy()
            thumb.thumbnail(self.thumbnail_size, Image.Resampling.LANCZOS)
            thumb_filename = (
                f"{filename.split('_')[0]}_thumb_{secrets.token_hex(8)}.jpg"
            )
            thumb_filepath = self.base_path / thumb_filename
            thumb.save(thumb_filepath, "JPEG", quality=85, optimize=True)

            # Return relative paths
            return True, {
                "avatar": f"/uploads/avatars/{filename}",
                "thumbnail": f"/uploads/avatars/{thumb_filename}",
            }

        except Exception as e:
            logger.error(f"Error saving locally: {e}")
            return False, f"Failed to save locally: {str(e)}"

    def delete_avatar(
        self, avatar_path: str, thumbnail_path: Optional[str] = None
    ) -> bool:
        """Delete user avatar files"""
        try:
            if self.use_s3:
                return self._delete_from_s3(avatar_path, thumbnail_path)
            else:
                return self._delete_from_local(avatar_path, thumbnail_path)

        except Exception as e:
            logger.error(f"Error deleting avatar: {e}")
            return False

    def _delete_from_s3(
        self, avatar_path: str, thumbnail_path: Optional[str] = None
    ) -> bool:
        """Delete avatar from S3"""
        try:
            # Extract S3 key from URL
            if avatar_path.startswith("https://"):
                if ".s3." in avatar_path and ".amazonaws.com/" in avatar_path:
                    # Handle region-specific URLs like https://bucket.s3.us-east-2.amazonaws.com/key
                    s3_key = avatar_path.split(".amazonaws.com/")[-1]
                elif "s3.amazonaws.com/" in avatar_path:
                    # Handle legacy URLs like https://bucket.s3.amazonaws.com/key
                    s3_key = avatar_path.split(".s3.amazonaws.com/")[-1]
                elif self.cloudfront_domain and self.cloudfront_domain in avatar_path:
                    s3_key = avatar_path.split(self.cloudfront_domain + "/")[-1]
                else:
                    logger.warning(f"Cannot extract S3 key from URL: {avatar_path}")
                    return False

                # Delete main avatar
                self.s3_client.delete_object(Bucket=self.bucket_name, Key=s3_key)

            # Delete thumbnail if provided
            if thumbnail_path and thumbnail_path.startswith("https://"):
                if ".s3." in thumbnail_path and ".amazonaws.com/" in thumbnail_path:
                    thumb_s3_key = thumbnail_path.split(".amazonaws.com/")[-1]
                elif "s3.amazonaws.com/" in thumbnail_path:
                    thumb_s3_key = thumbnail_path.split(".s3.amazonaws.com/")[-1]
                elif (
                    self.cloudfront_domain and self.cloudfront_domain in thumbnail_path
                ):
                    thumb_s3_key = thumbnail_path.split(self.cloudfront_domain + "/")[
                        -1
                    ]
                else:
                    logger.warning(
                        f"Cannot extract S3 key from thumbnail URL: {thumbnail_path}"
                    )
                    return True  # Don't fail if we can't delete thumbnail

                self.s3_client.delete_object(Bucket=self.bucket_name, Key=thumb_s3_key)

            return True

        except Exception as e:
            logger.error(f"Error deleting from S3: {e}")
            return False

    def _delete_from_local(
        self, avatar_path: str, thumbnail_path: Optional[str] = None
    ) -> bool:
        """Delete avatar from local filesystem"""
        try:
            # Delete main avatar
            if avatar_path and avatar_path.startswith("/uploads/avatars/"):
                filename = avatar_path.split("/")[-1]
                filepath = self.base_path / filename
                if filepath.exists():
                    filepath.unlink()

            # Delete thumbnail
            if thumbnail_path and thumbnail_path.startswith("/uploads/avatars/"):
                thumb_filename = thumbnail_path.split("/")[-1]
                thumb_filepath = self.base_path / thumb_filename
                if thumb_filepath.exists():
                    thumb_filepath.unlink()

            return True

        except Exception as e:
            logger.error(f"Error deleting from local: {e}")
            return False

    def get_avatar_url(self, user: dict, base_url: str = None) -> str:
        """Get user avatar URL or generate default"""
        if user.get("avatar_url"):
            # Return custom avatar
            if user["avatar_url"].startswith("http"):
                # S3 URLs or external URLs - return as-is
                return user["avatar_url"]
            else:
                # Local URLs - build full URL
                if base_url is None:
                    # Use environment-aware backend URL
                    if settings.ENVIRONMENT == "production":
                        base_url = "https://backend-production-f7af.up.railway.app"
                    elif settings.ENVIRONMENT == "staging":
                        base_url = "https://staging-backend.up.railway.app"
                    else:
                        base_url = "http://localhost:8001"
                return f"{base_url}{user['avatar_url']}"
        else:
            # Generate default avatar
            name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
            return self.generate_default_avatar(user["email"], name)

    def get_avatar_base64(self, filepath: str) -> Optional[str]:
        """Read avatar file and return as base64 data URL"""
        try:
            full_path = self.base_path / filepath.split("/")[-1]
            if full_path.exists():
                with open(full_path, "rb") as f:
                    image_bytes = f.read()
                    base64_image = base64.b64encode(image_bytes).decode("utf-8")
                    return f"data:image/jpeg;base64,{base64_image}"
            return None
        except Exception as e:
            logger.error(f"Error reading avatar: {e}")
            return None


# Service instance
avatar_service = AvatarService()
