"""
Database-powered authentication service using PostgreSQL
"""
import hashlib
import secrets
import json
from datetime import datetime, timedelta
from typing import Dict, Optional, List
import jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.database_models import User, UserSession
from app.services.totp_service import totp_service
from app.services.email_service import email_service
import logging

logger = logging.getLogger(__name__)

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class AuthServiceDB:
    """Database-powered user authentication and session management"""
    
    def __init__(self):
        self.pwd_context = pwd_context
        
        # Create demo users on initialization if they don't exist
        self._create_demo_users()
        
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
            db = SessionLocal()
            try:
                # Check if user already exists
                existing_user = db.query(User).filter(User.email == email).first()
                if existing_user:
                    return {"success": False, "error": "Email already registered"}
                
                # Create new user
                hashed_password = self.hash_password(password)
                verification_token = secrets.token_urlsafe(32)
                
                new_user = User(
                    email=email,
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
    
    async def authenticate_user(self, email: str, password: str) -> Dict:
        """Authenticate user login"""
        try:
            db = SessionLocal()
            try:
                user = db.query(User).filter(User.email == email).first()
                
                if not user:
                    return {"success": False, "error": "Invalid email or password"}
                
                if not self.verify_password(password, user.password_hash):
                    return {"success": False, "error": "Invalid email or password"}
                
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
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "subscription_tier": user.subscription_tier,
                    "is_verified": user.is_verified,
                    "is_admin": user.is_admin,
                    "favorite_teams": user.favorite_teams,
                    "preferred_sports": user.preferred_sports,
                    "notification_settings": user.notification_settings,
                    "avatar_url": user.avatar_url,
                    "avatar_thumbnail": user.avatar_thumbnail
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
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "subscription_tier": user.subscription_tier,
                    "is_verified": user.is_verified,
                    "is_admin": user.is_admin,
                    "avatar_url": user.avatar_url,
                    "avatar_thumbnail": user.avatar_thumbnail,
                    "favorite_teams": user.favorite_teams,
                    "preferred_sports": user.preferred_sports,
                    "notification_settings": user.notification_settings
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
                        User.first_name.ilike(f"%{search}%"),
                        User.last_name.ilike(f"%{search}%")
                    )
                    query = query.filter(search_filter)
                
                users = query.order_by(User.id).offset(skip).limit(limit).all()
                
                return [
                    {
                        "id": user.id,
                        "email": user.email,
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
                    existing_user = db.query(User).filter(User.email == user_data["email"]).first()
                    
                    if not existing_user:
                        hashed_password = self.hash_password(user_data["password"])
                        
                        new_user = User(
                            email=user_data["email"],
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
                
                # Store temporary secret (not enabled yet)
                # Note: In a real implementation, you'd add temp fields to the User model
                # For now, we'll store in a way that works with current model
                temp_data = {
                    "temp_totp_secret": secret,
                    "temp_backup_codes": backup_codes
                }
                # This is a simplified approach - in production you'd want dedicated temp fields
                
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

    async def enable_2fa(self, user_id: int, token: str, secret: str, backup_codes: List[str]) -> Dict:
        """Enable 2FA after verifying the setup token"""
        try:
            db = SessionLocal()
            try:
                user = db.query(User).filter(User.id == user_id).first()
                if not user:
                    return {"success": False, "error": "User not found"}
                
                if user.totp_enabled:
                    return {"success": False, "error": "2FA is already enabled"}
                
                # Verify the token
                if not totp_service.verify_token(secret, token):
                    return {"success": False, "error": "Invalid verification code"}
                
                # Enable 2FA
                user.totp_enabled = True
                user.totp_secret = secret
                user.backup_codes = backup_codes
                user.totp_last_used = datetime.utcnow()
                
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

# Initialize service
auth_service_db = AuthServiceDB()