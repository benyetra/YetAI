# app/services/avatar_service.py
"""Avatar service for handling user profile pictures"""

import os
import hashlib
import logging
from pathlib import Path
from typing import Optional, Tuple
import base64
from PIL import Image
import io
import secrets

logger = logging.getLogger(__name__)

class AvatarService:
    """Handle user avatar/profile picture operations"""
    
    def __init__(self):
        # Set up paths
        self.base_path = Path(__file__).parent.parent / "uploads" / "avatars"
        self.base_path.mkdir(parents=True, exist_ok=True)
        
        # Avatar settings
        self.max_size = (400, 400)  # Maximum dimensions
        self.thumbnail_size = (100, 100)  # Thumbnail dimensions
        self.allowed_formats = {'PNG', 'JPEG', 'JPG', 'GIF', 'WEBP'}
        self.max_file_size = 5 * 1024 * 1024  # 5MB
        
        # Default avatars (generated based on initials)
        self.default_colors = [
            '#A855F7',  # Purple
            '#F59E0B',  # Orange
            '#3B82F6',  # Blue
            '#10B981',  # Green
            '#EF4444',  # Red
            '#8B5CF6',  # Violet
            '#EC4899',  # Pink
            '#14B8A6',  # Teal
        ]
    
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
        email_hash = hashlib.md5(email.encode()).hexdigest()
        color_index = int(email_hash[:2], 16) % len(self.default_colors)
        bg_color = self.default_colors[color_index]
        
        # Create SVG
        svg = f'''
        <svg width="100" height="100" xmlns="http://www.w3.org/2000/svg">
            <rect width="100" height="100" fill="{bg_color}" rx="50"/>
            <text x="50" y="50" font-family="Arial, sans-serif" font-size="36" 
                  fill="white" text-anchor="middle" dominant-baseline="central">
                {initials}
            </text>
        </svg>
        '''
        
        # Convert to base64 data URL
        svg_bytes = svg.strip().encode('utf-8')
        base64_svg = base64.b64encode(svg_bytes).decode('utf-8')
        return f"data:image/svg+xml;base64,{base64_svg}"
    
    def save_avatar(self, user_id: int, image_data: str) -> Tuple[bool, str]:
        """Save user avatar from base64 data or file upload"""
        try:
            # Parse data URL or base64 string
            if image_data.startswith('data:'):
                # Extract base64 data from data URL
                header, data = image_data.split(',', 1)
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
                    return False, f"Invalid image format. Allowed: {', '.join(self.allowed_formats)}"
                
                # Convert RGBA to RGB if necessary (for JPEG compatibility)
                if img.mode in ('RGBA', 'LA', 'P'):
                    # Create a white background
                    background = Image.new('RGB', img.size, (255, 255, 255))
                    if img.mode == 'P':
                        img = img.convert('RGBA')
                    background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                    img = background
                
                # Resize image to max dimensions while maintaining aspect ratio
                img.thumbnail(self.max_size, Image.Resampling.LANCZOS)
                
                # Generate filename
                filename = f"{user_id}_{secrets.token_hex(8)}.jpg"
                filepath = self.base_path / filename
                
                # Save main image
                img.save(filepath, 'JPEG', quality=85, optimize=True)
                
                # Create and save thumbnail
                thumb = img.copy()
                thumb.thumbnail(self.thumbnail_size, Image.Resampling.LANCZOS)
                thumb_filename = f"{user_id}_thumb_{secrets.token_hex(8)}.jpg"
                thumb_filepath = self.base_path / thumb_filename
                thumb.save(thumb_filepath, 'JPEG', quality=85, optimize=True)
                
                # Return relative paths
                return True, {
                    'avatar': f"/uploads/avatars/{filename}",
                    'thumbnail': f"/uploads/avatars/{thumb_filename}"
                }
                
            except Exception as e:
                logger.error(f"Error processing image: {e}")
                return False, "Invalid image file"
                
        except Exception as e:
            logger.error(f"Error saving avatar: {e}")
            return False, "Failed to save avatar"
    
    def delete_avatar(self, avatar_path: str, thumbnail_path: Optional[str] = None) -> bool:
        """Delete user avatar files"""
        try:
            # Delete main avatar
            if avatar_path and avatar_path.startswith('/uploads/avatars/'):
                filename = avatar_path.split('/')[-1]
                filepath = self.base_path / filename
                if filepath.exists():
                    filepath.unlink()
            
            # Delete thumbnail
            if thumbnail_path and thumbnail_path.startswith('/uploads/avatars/'):
                thumb_filename = thumbnail_path.split('/')[-1]
                thumb_filepath = self.base_path / thumb_filename
                if thumb_filepath.exists():
                    thumb_filepath.unlink()
            
            return True
            
        except Exception as e:
            logger.error(f"Error deleting avatar: {e}")
            return False
    
    def get_avatar_url(self, user: dict, base_url: str = "http://localhost:8000") -> str:
        """Get user avatar URL or generate default"""
        if user.get('avatar_url'):
            # Return custom avatar
            if user['avatar_url'].startswith('http'):
                return user['avatar_url']
            else:
                return f"{base_url}{user['avatar_url']}"
        else:
            # Generate default avatar
            name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
            return self.generate_default_avatar(user['email'], name)
    
    def get_avatar_base64(self, filepath: str) -> Optional[str]:
        """Read avatar file and return as base64 data URL"""
        try:
            full_path = self.base_path / filepath.split('/')[-1]
            if full_path.exists():
                with open(full_path, 'rb') as f:
                    image_bytes = f.read()
                    base64_image = base64.b64encode(image_bytes).decode('utf-8')
                    return f"data:image/jpeg;base64,{base64_image}"
            return None
        except Exception as e:
            logger.error(f"Error reading avatar: {e}")
            return None

# Service instance
avatar_service = AvatarService()