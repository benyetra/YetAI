# app/services/totp_service.py
"""Two-Factor Authentication (2FA) service using TOTP"""

import pyotp
import qrcode
import secrets
import json
import io
import base64
from typing import Dict, List, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class TOTPService:
    """Handle TOTP (Time-based One-Time Password) operations for 2FA"""
    
    def __init__(self):
        self.issuer_name = "YetAI Sports Betting"
    
    def generate_secret(self) -> str:
        """Generate a new TOTP secret"""
        return pyotp.random_base32()
    
    def generate_qr_code_data(self, email: str, secret: str) -> str:
        """Generate QR code data URI for TOTP setup"""
        try:
            totp = pyotp.TOTP(secret)
            provisioning_uri = totp.provisioning_uri(
                name=email,
                issuer_name=self.issuer_name
            )
            
            # Generate QR code
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=10,
                border=4,
            )
            qr.add_data(provisioning_uri)
            qr.make(fit=True)
            
            # Create image
            img = qr.make_image(fill_color="black", back_color="white")
            
            # Convert to base64 data URI
            buffer = io.BytesIO()
            img.save(buffer, format='PNG')
            buffer.seek(0)
            
            img_str = base64.b64encode(buffer.getvalue()).decode()
            return f"data:image/png;base64,{img_str}"
            
        except Exception as e:
            logger.error(f"Error generating QR code: {e}")
            return None
    
    def verify_token(self, secret: str, token: str, last_used_time: Optional[datetime] = None) -> bool:
        """
        Verify a TOTP token
        
        Args:
            secret: The user's TOTP secret
            token: The 6-digit token to verify
            last_used_time: Last time a token was used (prevents replay attacks)
        
        Returns:
            bool: True if token is valid and not recently used
        """
        try:
            if not secret or not token:
                return False
            
            # Remove any spaces and ensure it's 6 digits
            token = token.replace(" ", "").strip()
            if len(token) != 6 or not token.isdigit():
                return False
            
            totp = pyotp.TOTP(secret)
            
            # Verify token with some time window tolerance
            current_time = datetime.utcnow()
            
            # Check if token is valid
            if not totp.verify(token, valid_window=1):  # Allow 1 window before/after for clock skew
                return False
            
            # Prevent replay attacks by checking if token was recently used
            if last_used_time:
                # Get current 30-second window
                current_window = int(current_time.timestamp()) // 30
                last_window = int(last_used_time.timestamp()) // 30
                
                if current_window <= last_window:
                    logger.warning("TOTP token replay attempt detected")
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error verifying TOTP token: {e}")
            return False
    
    def generate_backup_codes(self, count: int = 8) -> List[str]:
        """Generate backup codes for account recovery"""
        backup_codes = []
        for _ in range(count):
            # Generate 8-character alphanumeric codes
            code = ''.join(secrets.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789') for _ in range(8))
            backup_codes.append(code)
        return backup_codes
    
    def verify_backup_code(self, backup_codes: List[str], entered_code: str) -> tuple[bool, List[str]]:
        """
        Verify a backup code and remove it from the list
        
        Returns:
            tuple: (is_valid, updated_backup_codes_list)
        """
        try:
            if not backup_codes or not entered_code:
                return False, backup_codes
            
            # Normalize the entered code
            entered_code = entered_code.upper().replace(" ", "").replace("-", "")
            
            if entered_code in backup_codes:
                # Remove the used backup code
                updated_codes = [code for code in backup_codes if code != entered_code]
                return True, updated_codes
            
            return False, backup_codes
            
        except Exception as e:
            logger.error(f"Error verifying backup code: {e}")
            return False, backup_codes
    
    def get_current_token(self, secret: str) -> Optional[str]:
        """Get current TOTP token (for testing purposes only)"""
        try:
            if not secret:
                return None
            totp = pyotp.TOTP(secret)
            return totp.now()
        except Exception as e:
            logger.error(f"Error getting current token: {e}")
            return None

# Service instance
totp_service = TOTPService()