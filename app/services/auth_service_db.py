"""
Database-powered authentication service using PostgreSQL
"""
import hashlib
import secrets
import json
from datetime import datetime, timedelta
from typing import Dict, Optional, List
import jwt
import bcrypt
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.database_models import User, UserSession
from app.services.totp_service import totp_service
from app.services.email_service import email_service
import logging
import re

logger = logging.getLogger(__name__)

# Use bcrypt directly to avoid passlib version compatibility issues

class AuthServiceDB:
    """Database-powered user authentication and session management"""

    def __init__(self):
        # Create demo users on initialization if they don't exist
        self._create_demo_users()

    def hash_password(self, password: str) -> str:
        """Hash a password securely using bcrypt directly"""
        # Bcrypt has a 72-byte limit, truncate password if needed
        password_bytes = password.encode('utf-8')[:72]
        # Generate salt and hash
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(password_bytes, salt)
        return hashed.decode('utf-8')

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Verify a password against its hash using bcrypt directly"""
        # Apply same truncation as hash_password for consistency
        password_bytes = plain_password.encode('utf-8')[:72]
        hashed_bytes = hashed_password.encode('utf-8')
        return bcrypt.checkpw(password_bytes, hashed_bytes)
    
    def validate_username(self, username: str) -> Dict[str, str]:
        """Validate username format and availability"""
        # Check format
        if not username:
            return {"valid": False, "error": "Username is required"}
        
        if len(username) < 3:
            return {"valid": False, "error": "Username must be at least 3 characters long"}
        
        if len(username) > 50:
            return {"valid": False, "error": "Username must be less than 50 characters long"}
        
        # Check for valid characters (alphanumeric, underscore, hyphen)
        if not re.match(r'^[a-zA-Z0-9_-]+$', username):
            return {"valid": False, "error": "Username can only contain letters, numbers, underscores, and hyphens"}
        
        # Check if username starts with alphanumeric
        if not re.match(r'^[a-zA-Z0-9]', username):
            return {"valid": False, "error": "Username must start with a letter or number"}
        
        return {"valid": True}
    
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
    
    async def create_user(self, email: str, password: str, username: str, first_name: str = None, 
                         last_name: str = None) -> Dict:
        """Create a new user account"""
        try:
            # Validate username format
            username_validation = self.validate_username(username)
            if not username_validation["valid"]:
                return {"success": False, "error": username_validation["error"]}
            
            db = SessionLocal()
            try:
                # Check if user already exists by email or username
                existing_user = db.query(User).filter(
                    or_(User.email == email, User.username == username)
                ).first()
                if existing_user:
                    if existing_user.email == email:
                        return {"success": False, "error": "Email already registered"}
                    else:
                        return {"success": False, "error": "Username already taken"}
                
                # Create new user
                hashed_password = self.hash_password(password)
                verification_token = secrets.token_urlsafe(32)
                
                new_user = User(
                    email=email,
                    username=username,
                    password_hash=hashed_password,
                    first_name=first_name,
                    last_name=last_name,
                    subscription_tier="free",
                    favorite_teams=[],
                    preferred_sports=["americanfootball_nfl"],
                    notification_settings={"email": True, "push": False},
                    is_active=True,
                    is_verified=False,
                    verification_token=verification_token,
                    is_admin=False,
                    created_at=datetime.utcnow()
                )
                
                db.add(new_user)
                db.commit()
                db.refresh(new_user)
                
                # Send verification email
                try:
                    email_service.send_verification_email(
                        to_email=email,
                        verification_token=verification_token,
                        first_name=first_name
                    )
                except Exception as email_error:
                    logger.warning(f"Failed to send verification email: {email_error}")
                
                # Generate access token
                access_token = self.generate_token(new_user.id)
                
                return {
                    "success": True,
                    "user": {
                        "id": new_user.id,
                        "email": new_user.email,
                        "username": new_user.username,
                        "first_name": new_user.first_name,
                        "last_name": new_user.last_name,
                        "subscription_tier": new_user.subscription_tier,
                        "is_verified": new_user.is_verified,
                        "is_admin": new_user.is_admin,
                        "avatar_url": new_user.avatar_url,
                        "avatar_thumbnail": new_user.avatar_thumbnail
                    },
                    "access_token": access_token,
                    "token_type": "bearer"
                }
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error creating user: {e}")
            return {"success": False, "error": "Failed to create account"}
    
    async def authenticate_user(self, email_or_username: str, password: str) -> Dict:
        """Authenticate user login with email or username"""
        try:
            db = SessionLocal()
            try:
                # Try to find user by email or username
                user = db.query(User).filter(
                    or_(User.email == email_or_username, User.username == email_or_username)
                ).first()
                
                if not user:
                    return {"success": False, "error": "Invalid email/username or password"}
                
                if not self.verify_password(password, user.password_hash):
                    return {"success": False, "error": "Invalid email/username or password"}
                
                if not user.is_active:
                    return {"success": False, "error": "Account is deactivated"}
                
                # Update last login
                user.last_login = datetime.utcnow()
                db.commit()
                
                # Generate access token
                access_token = self.generate_token(user.id)
                
                return {
                    "success": True,
                    "user": {
                        "id": user.id,
                        "email": user.email,
                        "username": user.username,
                        "first_name": user.first_name,
                        "last_name": user.last_name,
                        "subscription_tier": user.subscription_tier,
                        "is_verified": user.is_verified,
                        "is_admin": user.is_admin,
                        "last_login": user.last_login.isoformat() if user.last_login else None,
                        "avatar_url": user.avatar_url,
                        "avatar_thumbnail": user.avatar_thumbnail
                    },
                    "access_token": access_token,
                    "token_type": "bearer"
                }
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error authenticating user: {e}")
            return {"success": False, "error": "Authentication failed"}
    
    async def get_user_by_token(self, token: str) -> Optional[Dict]:
        """Get user information from token"""
        try:
            user_id = self.verify_token(token)
            if not user_id:
                return None
            
            db = SessionLocal()
            try:
                user = db.query(User).filter(and_(User.id == user_id, User.is_active == True)).first()
                if not user:
                    return None
                
                return {
                    "id": user.id,
                    "email": user.email,
                    "username": user.username,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "subscription_tier": user.subscription_tier,
                    "is_verified": user.is_verified,
                    "is_admin": user.is_admin,
                    "favorite_teams": user.favorite_teams,
                    "preferred_sports": user.preferred_sports,
                    "notification_settings": user.notification_settings,
                    "avatar_url": user.avatar_url,
                    "avatar_thumbnail": user.avatar_thumbnail,
                    "totp_enabled": user.totp_enabled,
                    "backup_codes": user.backup_codes
                }
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error getting user by token: {e}")
            return None
    
    async def get_user_by_id(self, user_id: int) -> Optional[Dict]:
        """Get user information by ID"""
        try:
            db = SessionLocal()
            try:
                user = db.query(User).filter(and_(User.id == user_id, User.is_active == True)).first()
                if not user:
                    return None
                
                return {
                    "id": user.id,
                    "email": user.email,
                    "username": user.username,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "subscription_tier": user.subscription_tier,
                    "is_verified": user.is_verified,
                    "is_admin": user.is_admin,
                    "avatar_url": user.avatar_url,
                    "avatar_thumbnail": user.avatar_thumbnail,
                    "favorite_teams": user.favorite_teams,
                    "preferred_sports": user.preferred_sports,
                    "notification_settings": user.notification_settings,
                    "totp_enabled": user.totp_enabled,
                    "backup_codes": user.backup_codes
                }
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error getting user by ID: {e}")
            return None
    
    async def update_user_avatar(self, user_id: int, avatar_url: str, thumbnail_url: str) -> Dict:
        """Update user avatar URLs"""
        try:
            db = SessionLocal()
            try:
                user = db.query(User).filter(User.id == user_id).first()
                if not user:
                    return {"success": False, "error": "User not found"}
                
                user.avatar_url = avatar_url
                user.avatar_thumbnail = thumbnail_url
                db.commit()
                
                return {"success": True, "message": "Avatar updated"}
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error updating user avatar: {e}")
            return {"success": False, "error": "Failed to update avatar"}
    
    async def update_user_preferences(self, user_id: int, preferences: Dict) -> Dict:
        """Update user preferences"""
        try:
            db = SessionLocal()
            try:
                user = db.query(User).filter(User.id == user_id).first()
                if not user:
                    return {"success": False, "error": "User not found"}
                
                # Update preferences
                if "favorite_teams" in preferences:
                    user.favorite_teams = preferences["favorite_teams"]
                
                if "preferred_sports" in preferences:
                    user.preferred_sports = preferences["preferred_sports"]
                
                if "notification_settings" in preferences:
                    user.notification_settings = preferences["notification_settings"]
                
                if "first_name" in preferences:
                    user.first_name = preferences["first_name"]
                
                if "last_name" in preferences:
                    user.last_name = preferences["last_name"]
                
                if "username" in preferences:
                    # Check if username is already taken by another user
                    existing_user = db.query(User).filter(
                        and_(User.username == preferences["username"], User.id != user_id)
                    ).first()
                    if existing_user:
                        return {"success": False, "error": "Username already taken"}
                    user.username = preferences["username"]
                
                db.commit()
                
                return {"success": True, "message": "Preferences updated"}
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error updating user preferences: {e}")
            return {"success": False, "error": "Failed to update preferences"}
    
    async def upgrade_subscription(self, user_id: int, tier: str, expires_at: datetime = None) -> Dict:
        """Upgrade user subscription"""
        try:
            db = SessionLocal()
            try:
                user = db.query(User).filter(User.id == user_id).first()
                if not user:
                    return {"success": False, "error": "User not found"}
                
                user.subscription_tier = tier
                if expires_at:
                    user.subscription_expires_at = expires_at
                else:
                    # Default to 30 days from now
                    user.subscription_expires_at = datetime.utcnow() + timedelta(days=30)
                
                db.commit()
                
                return {"success": True, "message": f"Upgraded to {tier} tier"}
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error upgrading subscription: {e}")
            return {"success": False, "error": "Failed to upgrade subscription"}
    
    async def get_user_by_email(self, email: str) -> Optional[Dict]:
        """Get user by email address"""
        try:
            db = SessionLocal()
            try:
                user = db.query(User).filter(User.email == email).first()
                if user:
                    return {
                        "id": user.id,
                        "email": user.email,
                        "first_name": user.first_name,
                        "last_name": user.last_name,
                        "subscription_tier": user.subscription_tier,
                        "is_verified": user.is_verified,
                        "is_admin": user.is_admin,
                        "password_hash": user.password_hash,
                        "verification_token": user.verification_token,
                        "reset_token": user.reset_token,
                        "reset_token_expires": user.reset_token_expires
                    }
                return None
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error getting user by email: {e}")
            return None
    
    async def get_all_users(self, skip: int = 0, limit: int = 100, search: str = None) -> List[Dict]:
        """Get all users with optional search"""
        try:
            db = SessionLocal()
            try:
                query = db.query(User)
                
                if search:
                    search_filter = or_(
                        User.email.ilike(f"%{search}%"),
                        User.username.ilike(f"%{search}%"),
                        User.first_name.ilike(f"%{search}%"),
                        User.last_name.ilike(f"%{search}%")
                    )
                    query = query.filter(search_filter)
                
                users = query.order_by(User.id).offset(skip).limit(limit).all()
                
                return [
                    {
                        "id": user.id,
                        "email": user.email,
                        "username": user.username,
                        "first_name": user.first_name or "",
                        "last_name": user.last_name or "",
                        "subscription_tier": user.subscription_tier,
                        "is_admin": user.is_admin,
                        "is_verified": user.is_verified,
                        "created_at": user.created_at.isoformat() if user.created_at else "",
                        "last_login": user.last_login.isoformat() if user.last_login else "",
                        "totp_enabled": user.totp_enabled
                    } for user in users
                ]
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error getting all users: {e}")
            return []
    
    def _create_demo_users(self):
        """Create demo users if they don't exist"""
        try:
            db = SessionLocal()
            try:
                demo_users = [
                    {
                        "email": "demo@example.com",
                        "username": "demouser",
                        "password": "demo123",
                        "first_name": "Demo",
                        "last_name": "User",
                        "tier": "free"
                    },
                    {
                        "email": "pro@example.com", 
                        "username": "prouser",
                        "password": "pro123",
                        "first_name": "Pro",
                        "last_name": "User",
                        "tier": "pro"
                    },
                    {
                        "email": "admin@example.com", 
                        "username": "admin",
                        "password": "admin123",
                        "first_name": "Admin",
                        "last_name": "User",
                        "tier": "elite",
                        "is_admin": True
                    }
                ]
                
                for user_data in demo_users:
                    # Check if user already exists
                    existing_user = db.query(User).filter(User.email == user_data["email"]).first()
                    
                    if not existing_user:
                        hashed_password = self.hash_password(user_data["password"])
                        
                        new_user = User(
                            email=user_data["email"],
                            username=user_data["username"],
                            password_hash=hashed_password,
                            first_name=user_data["first_name"],
                            last_name=user_data["last_name"],
                            subscription_tier=user_data["tier"],
                            favorite_teams=["KC", "BUF"],
                            preferred_sports=["americanfootball_nfl"],
                            notification_settings={"email": True, "push": True},
                            is_active=True,
                            is_verified=True,
                            is_admin=user_data.get("is_admin", False),
                            created_at=datetime.utcnow()
                        )
                        
                        db.add(new_user)
                
                db.commit()
                logger.info("Demo users created successfully")
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error creating demo users: {e}")
    
    # 2FA methods (keeping existing implementation but using database)
    async def setup_2fa(self, user_id: int) -> Dict:
        """Generate 2FA setup data (secret, QR code, backup codes)"""
        try:
            db = SessionLocal()
            try:
                user = db.query(User).filter(User.id == user_id).first()
                if not user:
                    return {"success": False, "error": "User not found"}
                
                if user.totp_enabled:
                    return {"success": False, "error": "2FA is already enabled"}
                
                # Generate secret and QR code
                secret = totp_service.generate_secret()
                qr_code = totp_service.generate_qr_code_data(user.email, secret)
                backup_codes = totp_service.generate_backup_codes()
                
                if not qr_code:
                    return {"success": False, "error": "Failed to generate QR code"}
                
                # Store temporary secret and backup codes (not enabled yet)
                user.temp_totp_secret = secret
                user.temp_backup_codes = backup_codes
                db.commit()
                
                return {
                    "success": True,
                    "secret": secret,
                    "qr_code": qr_code,
                    "backup_codes": backup_codes
                }
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error setting up 2FA: {e}")
            return {"success": False, "error": "Failed to setup 2FA"}

    async def enable_2fa(self, user_id: int, token: str) -> Dict:
        """Enable 2FA after verifying the setup token"""
        try:
            db = SessionLocal()
            try:
                user = db.query(User).filter(User.id == user_id).first()
                if not user:
                    return {"success": False, "error": "User not found"}
                
                if user.totp_enabled:
                    return {"success": False, "error": "2FA is already enabled"}
                
                # Check if we have temp setup data
                temp_secret = user.temp_totp_secret
                if not temp_secret:
                    return {"success": False, "error": "No 2FA setup in progress"}
                
                # Verify the token
                if not totp_service.verify_token(temp_secret, token):
                    return {"success": False, "error": "Invalid verification code"}
                
                # Enable 2FA
                user.totp_enabled = True
                user.totp_secret = temp_secret
                user.backup_codes = user.temp_backup_codes or []
                user.totp_last_used = datetime.utcnow()
                
                # Clear temporary data
                user.temp_totp_secret = None
                user.temp_backup_codes = None
                
                db.commit()
                
                return {"success": True, "message": "2FA enabled successfully"}
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error enabling 2FA: {e}")
            return {"success": False, "error": "Failed to enable 2FA"}

    async def get_2fa_status(self, user_id: int) -> Dict:
        """Get 2FA status for a user"""
        try:
            db = SessionLocal()
            try:
                user = db.query(User).filter(User.id == user_id).first()
                if not user:
                    return {"success": False, "error": "User not found"}
                
                backup_codes_count = 0
                if user.backup_codes:
                    backup_codes_count = len(user.backup_codes)
                
                return {
                    "success": True,
                    "enabled": user.totp_enabled or False,
                    "backup_codes_remaining": backup_codes_count,
                    "setup_in_progress": False  # Would need temp fields for this
                }
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error getting 2FA status: {e}")
            return {"success": False, "error": "Failed to get 2FA status"}

    async def update_user(self, user_id: int, update_data: Dict) -> Optional[Dict]:
        """Update user information"""
        try:
            logger.info(f"Attempting to update user {user_id} with data: {update_data}")
            db = SessionLocal()
            try:
                # Get the user
                user = db.query(User).filter(User.id == user_id).first()
                if not user:
                    logger.warning(f"User with ID {user_id} not found in database")
                    return None
                
                logger.info(f"Found user: {user.email} (ID: {user.id})")

                # Update fields if provided
                if "email" in update_data:
                    user.email = update_data["email"]
                
                if "username" in update_data:
                    # Validate username format
                    validation = self.validate_username(update_data["username"])
                    if not validation["valid"]:
                        raise ValueError(validation["error"])
                    
                    # Check if username is already taken by another user
                    existing_user = db.query(User).filter(
                        and_(User.username == update_data["username"], User.id != user_id)
                    ).first()
                    if existing_user:
                        raise ValueError("Username is already taken")
                    
                    user.username = update_data["username"]
                
                if "first_name" in update_data:
                    user.first_name = update_data["first_name"]
                
                if "last_name" in update_data:
                    user.last_name = update_data["last_name"]
                
                if "password" in update_data:
                    user.password_hash = self.hash_password(update_data["password"])
                
                if "subscription_tier" in update_data:
                    # Validate subscription tier
                    valid_tiers = ["free", "pro", "elite"]
                    if update_data["subscription_tier"] not in valid_tiers:
                        raise ValueError(f"Invalid subscription tier. Must be one of: {', '.join(valid_tiers)}")
                    user.subscription_tier = update_data["subscription_tier"]
                
                if "is_admin" in update_data:
                    user.is_admin = update_data["is_admin"]
                
                if "is_verified" in update_data:
                    user.is_verified = update_data["is_verified"]
                
                if "totp_enabled" in update_data:
                    user.totp_enabled = update_data["totp_enabled"]
                    if not update_data["totp_enabled"]:
                        # If disabling 2FA, clear related fields
                        user.totp_secret = None
                        user.backup_codes = None
                        user.totp_last_used = None

                # Commit changes
                db.commit()
                db.refresh(user)
                
                logger.info(f"Successfully updated user {user_id}. New values: is_admin={user.is_admin}, subscription_tier={user.subscription_tier}")
                
                return {
                    "id": user.id,
                    "email": user.email,
                    "username": user.username,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "subscription_tier": user.subscription_tier,
                    "is_verified": user.is_verified,
                    "is_admin": user.is_admin,
                    "totp_enabled": user.totp_enabled,
                    "avatar_url": user.avatar_url,
                    "avatar_thumbnail": user.avatar_thumbnail,
                    "created_at": user.created_at.isoformat() if user.created_at else None,
                    "last_login": user.last_login.isoformat() if user.last_login else None
                }
                
            finally:
                db.close()
                
        except ValueError as e:
            logger.error(f"Validation error updating user {user_id}: {e}")
            raise e
        except Exception as e:
            logger.error(f"Error updating user {user_id}: {e}")
            return None

    async def delete_user(self, user_id: int) -> bool:
        """Delete a user and all associated data"""
        try:
            logger.info(f"Attempting to delete user {user_id}")
            db = SessionLocal()
            try:
                # Get the user
                user = db.query(User).filter(User.id == user_id).first()
                if not user:
                    logger.warning(f"User with ID {user_id} not found in database")
                    return False

                logger.info(f"Found user to delete: {user.email} (ID: {user.id})")

                # Delete user sessions first (foreign key constraint)
                db.query(UserSession).filter(UserSession.user_id == user_id).delete()

                # Delete the user
                db.delete(user)
                db.commit()

                logger.info(f"Successfully deleted user {user_id}")
                return True

            finally:
                db.close()

        except Exception as e:
            logger.error(f"Error deleting user {user_id}: {e}")
            return False

    async def verify_email(self, token: str) -> Dict:
        """Verify user email with verification token"""
        try:
            db = SessionLocal()
            try:
                user = db.query(User).filter(User.verification_token == token).first()
                if not user:
                    return {"success": False, "error": "Invalid or expired verification token"}

                if user.is_verified:
                    return {"success": False, "error": "Email is already verified"}

                # Verify the email
                user.is_verified = True
                user.verification_token = None  # Clear the token
                db.commit()

                return {
                    "success": True,
                    "message": "Email verified successfully",
                    "user": {
                        "id": user.id,
                        "email": user.email,
                        "username": user.username,
                        "is_verified": user.is_verified
                    }
                }

            finally:
                db.close()

        except Exception as e:
            logger.error(f"Error verifying email: {e}")
            return {"success": False, "error": "Failed to verify email"}

    async def resend_verification_email(self, email: str) -> Dict:
        """Resend verification email to user"""
        try:
            db = SessionLocal()
            try:
                user = db.query(User).filter(User.email == email).first()
                if not user:
                    return {"success": False, "error": "User not found"}

                if user.is_verified:
                    return {"success": False, "error": "Email is already verified"}

                # Generate new verification token
                verification_token = secrets.token_urlsafe(32)
                user.verification_token = verification_token
                db.commit()

                # Send verification email
                try:
                    email_service.send_verification_email(
                        to_email=email,
                        verification_token=verification_token,
                        first_name=user.first_name
                    )
                    return {"success": True, "message": "Verification email sent"}
                except Exception as email_error:
                    logger.error(f"Failed to send verification email: {email_error}")
                    return {"success": False, "error": "Failed to send verification email"}

            finally:
                db.close()

        except Exception as e:
            logger.error(f"Error resending verification email: {e}")
            return {"success": False, "error": "Failed to resend verification email"}

    async def request_password_reset(self, email: str) -> Dict:
        """Request password reset for user"""
        try:
            db = SessionLocal()
            try:
                user = db.query(User).filter(User.email == email).first()
                if not user:
                    # Don't reveal if email exists for security
                    return {"success": True, "message": "If the email exists, a reset link has been sent"}

                # Generate reset token with 1 hour expiry
                reset_token = secrets.token_urlsafe(32)
                reset_expires = datetime.utcnow() + timedelta(hours=1)

                user.reset_token = reset_token
                user.reset_token_expires = reset_expires
                db.commit()

                # Send password reset email
                try:
                    email_service.send_password_reset_email(
                        to_email=email,
                        reset_token=reset_token,
                        first_name=user.first_name
                    )
                    return {"success": True, "message": "If the email exists, a reset link has been sent"}
                except Exception as email_error:
                    logger.error(f"Failed to send password reset email: {email_error}")
                    return {"success": False, "error": "Failed to send password reset email"}

            finally:
                db.close()

        except Exception as e:
            logger.error(f"Error requesting password reset: {e}")
            return {"success": False, "error": "Failed to request password reset"}

    async def reset_password(self, token: str, new_password: str) -> Dict:
        """Reset user password with reset token"""
        try:
            db = SessionLocal()
            try:
                user = db.query(User).filter(
                    and_(
                        User.reset_token == token,
                        User.reset_token_expires > datetime.utcnow()
                    )
                ).first()

                if not user:
                    return {"success": False, "error": "Invalid or expired reset token"}

                # Reset password
                user.password_hash = self.hash_password(new_password)
                user.reset_token = None  # Clear reset token
                user.reset_token_expires = None
                db.commit()

                return {
                    "success": True,
                    "message": "Password reset successfully",
                    "user": {
                        "id": user.id,
                        "email": user.email,
                        "username": user.username
                    }
                }

            finally:
                db.close()

        except Exception as e:
            logger.error(f"Error resetting password: {e}")
            return {"success": False, "error": "Failed to reset password"}

# Initialize service
auth_service_db = AuthServiceDB()