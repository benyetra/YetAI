# app/services/auth_service.py
"""Simple but secure user authentication system with in-memory storage"""

import hashlib
import secrets
import json
from datetime import datetime, timedelta
from typing import Dict, Optional, List
import jwt
from passlib.context import CryptContext
from app.core.config import settings
from app.services.totp_service import totp_service
import logging

logger = logging.getLogger(__name__)

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class AuthService:
    """Handle user authentication and session management with in-memory storage"""
    
    def __init__(self):
        # In-memory user storage (replace with database in production)
        self.users = {}
        self.user_id_counter = 1
        
        # Create demo users immediately
        self.create_demo_users()
    
    def hash_password(self, password: str) -> str:
        """Hash a password securely"""
        return pwd_context.hash(password)
    
    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Verify a password against its hash"""
        return pwd_context.verify(plain_password, hashed_password)
    
    def generate_token(self, user_id: int, expires_delta: timedelta = None) -> str:
        """Generate a JWT token for user"""
        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        
        to_encode = {"sub": str(user_id), "exp": expire}
        encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
        return encoded_jwt
    
    def verify_token(self, token: str) -> Optional[int]:
        """Verify a JWT token and return user ID"""
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
            user_id: str = payload.get("sub")
            if user_id is None:
                return None
            return int(user_id)
        except jwt.PyJWTError:
            return None
    
    async def create_user(self, email: str, password: str, first_name: str = None, 
                         last_name: str = None) -> Dict:
        """Create a new user account"""
        try:
            # Check if user already exists
            for user in self.users.values():
                if user["email"] == email:
                    return {"success": False, "error": "Email already registered"}
            
            # Create new user
            user_id = self.user_id_counter
            self.user_id_counter += 1
            
            hashed_password = self.hash_password(password)
            
            new_user = {
                "id": user_id,
                "email": email,
                "password_hash": hashed_password,
                "first_name": first_name,
                "last_name": last_name,
                "subscription_tier": "free",
                "subscription_expires_at": None,
                "stripe_customer_id": None,
                "favorite_teams": "[]",
                "preferred_sports": "[\"NFL\"]",
                "notification_settings": "{\"email\": true, \"push\": false}",
                "is_active": True,
                "is_verified": False,
                "verification_token": secrets.token_urlsafe(32),
                "is_admin": False,
                "created_at": datetime.utcnow(),
                "last_login": None,
                # 2FA fields
                "totp_enabled": False,
                "totp_secret": None,
                "backup_codes": None,
                "totp_last_used": None
            }
            
            self.users[user_id] = new_user
            
            # Generate access token
            access_token = self.generate_token(new_user["id"])
            
            return {
                "success": True,
                "user": {
                    "id": new_user["id"],
                    "email": new_user["email"],
                    "first_name": new_user["first_name"],
                    "last_name": new_user["last_name"],
                    "subscription_tier": new_user["subscription_tier"],
                    "is_verified": new_user["is_verified"],
                    "is_admin": new_user["is_admin"]
                },
                "access_token": access_token,
                "token_type": "bearer"
            }
            
        except Exception as e:
            logger.error(f"Error creating user: {e}")
            return {"success": False, "error": "Failed to create account"}
    
    async def authenticate_user(self, email: str, password: str) -> Dict:
        """Authenticate user login"""
        try:
            user = None
            for u in self.users.values():
                if u["email"] == email:
                    user = u
                    break
            
            if not user:
                return {"success": False, "error": "Invalid email or password"}
            
            if not self.verify_password(password, user["password_hash"]):
                return {"success": False, "error": "Invalid email or password"}
            
            if not user["is_active"]:
                return {"success": False, "error": "Account is deactivated"}
            
            # Update last login
            user["last_login"] = datetime.utcnow()
            
            # Generate access token
            access_token = self.generate_token(user["id"])
            
            return {
                "success": True,
                "user": {
                    "id": user["id"],
                    "email": user["email"],
                    "first_name": user["first_name"],
                    "last_name": user["last_name"],
                    "subscription_tier": user["subscription_tier"],
                    "is_verified": user["is_verified"],
                    "is_admin": user["is_admin"],
                    "last_login": user["last_login"].isoformat() if user["last_login"] else None
                },
                "access_token": access_token,
                "token_type": "bearer"
            }
            
        except Exception as e:
            logger.error(f"Error authenticating user: {e}")
            return {"success": False, "error": "Authentication failed"}
    
    async def get_user_by_token(self, token: str) -> Optional[Dict]:
        """Get user information from token"""
        try:
            user_id = self.verify_token(token)
            if not user_id:
                return None
            
            user = self.users.get(user_id)
            if not user or not user["is_active"]:
                return None
            
            return {
                "id": user["id"],
                "email": user["email"],
                "first_name": user["first_name"],
                "last_name": user["last_name"],
                "subscription_tier": user["subscription_tier"],
                "is_verified": user["is_verified"],
                "is_admin": user["is_admin"],
                "favorite_teams": user["favorite_teams"],
                "preferred_sports": user["preferred_sports"],
                "notification_settings": user["notification_settings"]
            }
            
        except Exception as e:
            logger.error(f"Error getting user by token: {e}")
            return None
    
    async def update_user_preferences(self, user_id: int, preferences: Dict) -> Dict:
        """Update user preferences"""
        try:
            user = self.users.get(user_id)
            if not user:
                return {"success": False, "error": "User not found"}
            
            # Update preferences
            if "favorite_teams" in preferences:
                import json
                user["favorite_teams"] = json.dumps(preferences["favorite_teams"]) if isinstance(preferences["favorite_teams"], list) else str(preferences["favorite_teams"])
            
            if "preferred_sports" in preferences:
                import json
                user["preferred_sports"] = json.dumps(preferences["preferred_sports"]) if isinstance(preferences["preferred_sports"], list) else str(preferences["preferred_sports"])
            
            if "notification_settings" in preferences:
                import json
                user["notification_settings"] = json.dumps(preferences["notification_settings"]) if isinstance(preferences["notification_settings"], dict) else str(preferences["notification_settings"])
            
            if "first_name" in preferences:
                user["first_name"] = preferences["first_name"]
            
            if "last_name" in preferences:
                user["last_name"] = preferences["last_name"]
            
            return {"success": True, "message": "Preferences updated"}
            
        except Exception as e:
            logger.error(f"Error updating user preferences: {e}")
            return {"success": False, "error": "Failed to update preferences"}
    
    async def upgrade_subscription(self, user_id: int, tier: str, expires_at: datetime = None) -> Dict:
        """Upgrade user subscription"""
        try:
            user = self.users.get(user_id)
            if not user:
                return {"success": False, "error": "User not found"}
            
            user["subscription_tier"] = tier
            if expires_at:
                user["subscription_expires_at"] = expires_at
            else:
                # Default to 30 days from now
                user["subscription_expires_at"] = datetime.utcnow() + timedelta(days=30)
            
            return {"success": True, "message": f"Upgraded to {tier} tier"}
            
        except Exception as e:
            logger.error(f"Error upgrading subscription: {e}")
            return {"success": False, "error": "Failed to upgrade subscription"}
    
    def create_demo_users(self):
        """Create some demo users for testing"""
        try:
            demo_users = [
                {
                    "email": "demo@example.com",
                    "password": "demo123",
                    "first_name": "Demo",
                    "last_name": "User",
                    "tier": "free"
                },
                {
                    "email": "pro@example.com", 
                    "password": "pro123",
                    "first_name": "Pro",
                    "last_name": "User",
                    "tier": "pro"
                },
                {
                    "email": "admin@example.com", 
                    "password": "admin123",
                    "first_name": "Admin",
                    "last_name": "User",
                    "tier": "elite",
                    "is_admin": True
                }
            ]
            
            for user_data in demo_users:
                # Check if user already exists
                exists = False
                for user in self.users.values():
                    if user["email"] == user_data["email"]:
                        exists = True
                        break
                
                if not exists:
                    user_id = self.user_id_counter
                    self.user_id_counter += 1
                    
                    hashed_password = self.hash_password(user_data["password"])
                    
                    new_user = {
                        "id": user_id,
                        "email": user_data["email"],
                        "password_hash": hashed_password,
                        "first_name": user_data["first_name"],
                        "last_name": user_data["last_name"],
                        "subscription_tier": user_data["tier"],
                        "subscription_expires_at": None,
                        "stripe_customer_id": None,
                        "favorite_teams": "[\"KC\", \"BUF\"]",
                        "preferred_sports": "[\"NFL\"]",
                        "notification_settings": "{\"email\": true, \"push\": true}",
                        "is_active": True,
                        "is_verified": True,
                        "verification_token": None,
                        "is_admin": user_data.get("is_admin", False),
                        "created_at": datetime.utcnow(),
                        "last_login": None,
                        # 2FA fields
                        "totp_enabled": False,
                        "totp_secret": None,
                        "backup_codes": None,
                        "totp_last_used": None
                    }
                    
                    self.users[user_id] = new_user
            
            logger.info("Demo users created successfully")
            
        except Exception as e:
            logger.error(f"Error creating demo users: {e}")
    
    async def create_admin_user(self, email: str, password: str, first_name: str = None, last_name: str = None) -> Dict:
        """Create a new admin user"""
        try:
            # Check if user already exists
            for user in self.users.values():
                if user["email"] == email:
                    return {"success": False, "error": "Email already registered"}
            
            # Create new admin user
            user_id = self.user_id_counter
            self.user_id_counter += 1
            
            hashed_password = self.hash_password(password)
            
            new_admin = {
                "id": user_id,
                "email": email,
                "password_hash": hashed_password,
                "first_name": first_name,
                "last_name": last_name,
                "subscription_tier": "elite",  # Admins get elite tier
                "subscription_expires_at": None,
                "stripe_customer_id": None,
                "favorite_teams": "[]",
                "preferred_sports": "[\"NFL\"]",
                "notification_settings": "{\"email\": true, \"push\": true}",
                "is_active": True,
                "is_verified": True,
                "verification_token": None,
                "is_admin": True,  # This is the key field
                "created_at": datetime.utcnow(),
                "last_login": None,
                # 2FA fields
                "totp_enabled": False,
                "totp_secret": None,
                "backup_codes": None,
                "totp_last_used": None
            }
            
            self.users[user_id] = new_admin
            
            # Generate access token
            access_token = self.generate_token(new_admin["id"])
            
            return {
                "success": True,
                "user": {
                    "id": new_admin["id"],
                    "email": new_admin["email"],
                    "first_name": new_admin["first_name"],
                    "last_name": new_admin["last_name"],
                    "subscription_tier": new_admin["subscription_tier"],
                    "is_verified": new_admin["is_verified"],
                    "is_admin": new_admin["is_admin"]
                },
                "access_token": access_token,
                "token_type": "bearer"
            }
            
        except Exception as e:
            logger.error(f"Error creating admin user: {e}")
            return {"success": False, "error": "Failed to create admin account"}
    
    async def setup_2fa(self, user_id: int) -> Dict:
        """Generate 2FA setup data (secret, QR code, backup codes)"""
        try:
            user = self.users.get(user_id)
            if not user:
                return {"success": False, "error": "User not found"}
            
            if user.get("totp_enabled", False):
                return {"success": False, "error": "2FA is already enabled"}
            
            # Generate secret and QR code
            secret = totp_service.generate_secret()
            qr_code = totp_service.generate_qr_code_data(user["email"], secret)
            backup_codes = totp_service.generate_backup_codes()
            
            if not qr_code:
                return {"success": False, "error": "Failed to generate QR code"}
            
            # Store temporary secret (not enabled yet)
            user["temp_totp_secret"] = secret
            user["temp_backup_codes"] = json.dumps(backup_codes)
            
            return {
                "success": True,
                "secret": secret,
                "qr_code": qr_code,
                "backup_codes": backup_codes
            }
            
        except Exception as e:
            logger.error(f"Error setting up 2FA: {e}")
            return {"success": False, "error": "Failed to setup 2FA"}
    
    async def enable_2fa(self, user_id: int, token: str) -> Dict:
        """Enable 2FA after verifying the setup token"""
        try:
            user = self.users.get(user_id)
            if not user:
                return {"success": False, "error": "User not found"}
            
            if user.get("totp_enabled", False):
                return {"success": False, "error": "2FA is already enabled"}
            
            temp_secret = user.get("temp_totp_secret")
            if not temp_secret:
                return {"success": False, "error": "No 2FA setup in progress"}
            
            # Verify the token
            if not totp_service.verify_token(temp_secret, token):
                return {"success": False, "error": "Invalid verification code"}
            
            # Enable 2FA
            user["totp_enabled"] = True
            user["totp_secret"] = temp_secret
            user["backup_codes"] = user.get("temp_backup_codes")
            user["totp_last_used"] = datetime.utcnow()
            
            # Clean up temporary data
            user.pop("temp_totp_secret", None)
            user.pop("temp_backup_codes", None)
            
            return {"success": True, "message": "2FA enabled successfully"}
            
        except Exception as e:
            logger.error(f"Error enabling 2FA: {e}")
            return {"success": False, "error": "Failed to enable 2FA"}
    
    async def disable_2fa(self, user_id: int, password: str, token_or_backup: str) -> Dict:
        """Disable 2FA with password and 2FA verification"""
        try:
            user = self.users.get(user_id)
            if not user:
                return {"success": False, "error": "User not found"}
            
            if not user.get("totp_enabled", False):
                return {"success": False, "error": "2FA is not enabled"}
            
            # Verify password first
            if not self.verify_password(password, user["password_hash"]):
                return {"success": False, "error": "Invalid password"}
            
            # Verify 2FA token or backup code
            if not await self.verify_2fa_token(user_id, token_or_backup):
                return {"success": False, "error": "Invalid 2FA code"}
            
            # Disable 2FA
            user["totp_enabled"] = False
            user["totp_secret"] = None
            user["backup_codes"] = None
            user["totp_last_used"] = None
            
            return {"success": True, "message": "2FA disabled successfully"}
            
        except Exception as e:
            logger.error(f"Error disabling 2FA: {e}")
            return {"success": False, "error": "Failed to disable 2FA"}
    
    async def verify_2fa_token(self, user_id: int, token: str) -> bool:
        """Verify a 2FA token or backup code"""
        try:
            user = self.users.get(user_id)
            if not user or not user.get("totp_enabled", False):
                return False
            
            secret = user.get("totp_secret")
            last_used = user.get("totp_last_used")
            
            # Try TOTP token first
            if totp_service.verify_token(secret, token, last_used):
                user["totp_last_used"] = datetime.utcnow()
                return True
            
            # Try backup code
            backup_codes_str = user.get("backup_codes")
            if backup_codes_str:
                backup_codes = json.loads(backup_codes_str)
                is_valid, updated_codes = totp_service.verify_backup_code(backup_codes, token)
                if is_valid:
                    user["backup_codes"] = json.dumps(updated_codes)
                    return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error verifying 2FA token: {e}")
            return False
    
    async def get_2fa_status(self, user_id: int) -> Dict:
        """Get 2FA status for a user"""
        try:
            user = self.users.get(user_id)
            if not user:
                return {"success": False, "error": "User not found"}
            
            backup_codes_str = user.get("backup_codes")
            backup_codes_count = 0
            if backup_codes_str:
                backup_codes = json.loads(backup_codes_str)
                backup_codes_count = len(backup_codes)
            
            return {
                "success": True,
                "enabled": user.get("totp_enabled", False),
                "backup_codes_remaining": backup_codes_count,
                "setup_in_progress": "temp_totp_secret" in user
            }
            
        except Exception as e:
            logger.error(f"Error getting 2FA status: {e}")
            return {"success": False, "error": "Failed to get 2FA status"}

# Service instance
auth_service = AuthService()