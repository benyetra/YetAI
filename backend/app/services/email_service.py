# app/services/email_service.py
"""Email service for sending verification emails, password resets, etc."""

import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
import logging
from datetime import datetime, timedelta
import secrets
from app.core.config import settings

logger = logging.getLogger(__name__)


class EmailService:
    """Handle email sending for the application"""

    def __init__(self):
        # Email configuration - in production, use environment variables
        self.smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self.smtp_user = os.getenv("SMTP_USER", "")
        self.smtp_password = os.getenv("SMTP_PASSWORD", "")
        self.from_email = os.getenv("FROM_EMAIL", "noreply@yetai.com")
        self.from_name = "YetAI Sports Betting"
        # Use environment-aware frontend URL
        frontend_urls = settings.get_frontend_urls()
        self.app_url = frontend_urls[0] if frontend_urls else "http://localhost:3000"

        # For development - simulate email sending
        self.dev_mode = not self.smtp_user or not self.smtp_password

        if self.dev_mode:
            logger.info(
                "Email service running in development mode - emails will be logged only"
            )

    def send_email(
        self,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: Optional[str] = None,
    ) -> bool:
        """Send an email"""
        try:
            if self.dev_mode:
                # In development, just log the email
                logger.info(
                    f"""
                ========== EMAIL SIMULATION ==========
                To: {to_email}
                Subject: {subject}
                Body: {text_body or 'HTML email'}
                ======================================
                """
                )
                return True

            # Create message
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = f"{self.from_name} <{self.from_email}>"
            msg["To"] = to_email

            # Add text and HTML parts
            if text_body:
                part1 = MIMEText(text_body, "plain")
                msg.attach(part1)

            part2 = MIMEText(html_body, "html")
            msg.attach(part2)

            # Send email with timeout (30 seconds for Brevo SMTP relay)
            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=30) as server:
                server.starttls()
                server.login(self.smtp_user, self.smtp_password)
                server.send_message(msg)

            logger.info(f"Email sent successfully to {to_email}")
            return True

        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {e}")
            return False

    def send_verification_email(
        self, to_email: str, verification_token: str, first_name: Optional[str] = None
    ) -> bool:
        """Send email verification link"""
        verification_link = f"{self.app_url}/verify-email?token={verification_token}"

        subject = "Verify Your YetAI Account"

        html_body = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: linear-gradient(135deg, #A855F7 0%, #F59E0B 100%); color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }}
                .content {{ background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px; }}
                .button {{ display: inline-block; padding: 12px 30px; background: #A855F7; color: white; text-decoration: none; border-radius: 5px; margin: 20px 0; }}
                .footer {{ text-align: center; margin-top: 30px; color: #666; font-size: 12px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>Welcome to YetAI!</h1>
                </div>
                <div class="content">
                    <h2>Hi {first_name or 'there'},</h2>
                    <p>Thanks for signing up for YetAI Sports Betting Platform! Please verify your email address to activate your account and start using our AI-powered betting insights.</p>
                    <p style="text-align: center;">
                        <a href="{verification_link}" class="button">Verify Email Address</a>
                    </p>
                    <p>Or copy and paste this link into your browser:</p>
                    <p style="word-break: break-all; background: #fff; padding: 10px; border-radius: 5px;">{verification_link}</p>
                    <p>This link will expire in 24 hours for security reasons.</p>
                    <p>If you didn't create an account with YetAI, please ignore this email.</p>
                </div>
                <div class="footer">
                    <p>© 2024 YetAI Sports Betting Platform. All rights reserved.</p>
                    <p>This is an automated message, please do not reply.</p>
                </div>
            </div>
        </body>
        </html>
        """

        text_body = f"""
        Welcome to YetAI!
        
        Hi {first_name or 'there'},
        
        Thanks for signing up for YetAI Sports Betting Platform! Please verify your email address to activate your account.
        
        Verify your email by clicking this link:
        {verification_link}
        
        This link will expire in 24 hours.
        
        If you didn't create an account with YetAI, please ignore this email.
        
        © 2024 YetAI Sports Betting Platform
        """

        return self.send_email(to_email, subject, html_body, text_body)

    def send_password_reset_email(
        self, to_email: str, reset_token: str, first_name: Optional[str] = None
    ) -> bool:
        """Send password reset email"""
        reset_link = f"{self.app_url}/reset-password?token={reset_token}"

        subject = "Reset Your YetAI Password"

        html_body = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: linear-gradient(135deg, #A855F7 0%, #F59E0B 100%); color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }}
                .content {{ background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px; }}
                .button {{ display: inline-block; padding: 12px 30px; background: #A855F7; color: white; text-decoration: none; border-radius: 5px; margin: 20px 0; }}
                .warning {{ background: #FEF3C7; border-left: 4px solid #F59E0B; padding: 10px; margin: 20px 0; }}
                .footer {{ text-align: center; margin-top: 30px; color: #666; font-size: 12px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>Password Reset Request</h1>
                </div>
                <div class="content">
                    <h2>Hi {first_name or 'there'},</h2>
                    <p>We received a request to reset your YetAI account password. Click the button below to create a new password:</p>
                    <p style="text-align: center;">
                        <a href="{reset_link}" class="button">Reset Password</a>
                    </p>
                    <p>Or copy and paste this link into your browser:</p>
                    <p style="word-break: break-all; background: #fff; padding: 10px; border-radius: 5px;">{reset_link}</p>
                    <div class="warning">
                        <strong>Security Notice:</strong> This link will expire in 1 hour. If you didn't request a password reset, please ignore this email and your password will remain unchanged.
                    </div>
                </div>
                <div class="footer">
                    <p>© 2024 YetAI Sports Betting Platform. All rights reserved.</p>
                    <p>This is an automated message, please do not reply.</p>
                </div>
            </div>
        </body>
        </html>
        """

        text_body = f"""
        Password Reset Request
        
        Hi {first_name or 'there'},
        
        We received a request to reset your YetAI account password.
        
        Reset your password by clicking this link:
        {reset_link}
        
        This link will expire in 1 hour.
        
        If you didn't request a password reset, please ignore this email and your password will remain unchanged.
        
        © 2024 YetAI Sports Betting Platform
        """

        return self.send_email(to_email, subject, html_body, text_body)

    def send_2fa_backup_codes_email(
        self, to_email: str, backup_codes: list, first_name: Optional[str] = None
    ) -> bool:
        """Send 2FA backup codes via email"""
        subject = "Your YetAI 2FA Backup Codes"

        codes_html = "<br>".join([f"<code>{code}</code>" for code in backup_codes])
        codes_text = "\n".join([f"  • {code}" for code in backup_codes])

        html_body = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: linear-gradient(135deg, #A855F7 0%, #F59E0B 100%); color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }}
                .content {{ background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px; }}
                .codes {{ background: white; border: 2px solid #A855F7; padding: 20px; border-radius: 5px; margin: 20px 0; }}
                code {{ background: #f0f0f0; padding: 5px 10px; border-radius: 3px; font-size: 14px; display: inline-block; margin: 5px 0; }}
                .warning {{ background: #FEF3C7; border-left: 4px solid #F59E0B; padding: 10px; margin: 20px 0; }}
                .footer {{ text-align: center; margin-top: 30px; color: #666; font-size: 12px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>2FA Backup Codes</h1>
                </div>
                <div class="content">
                    <h2>Hi {first_name or 'there'},</h2>
                    <p>You've successfully enabled Two-Factor Authentication on your YetAI account. Here are your backup codes:</p>
                    <div class="codes">
                        {codes_html}
                    </div>
                    <div class="warning">
                        <strong>Important:</strong>
                        <ul style="margin: 10px 0;">
                            <li>Each code can only be used once</li>
                            <li>Store these codes in a safe place</li>
                            <li>Use these if you lose access to your authenticator app</li>
                            <li>Generate new codes if these are compromised</li>
                        </ul>
                    </div>
                </div>
                <div class="footer">
                    <p>© 2024 YetAI Sports Betting Platform. All rights reserved.</p>
                    <p>Keep this email secure - it contains sensitive information.</p>
                </div>
            </div>
        </body>
        </html>
        """

        text_body = f"""
        2FA Backup Codes for YetAI
        
        Hi {first_name or 'there'},
        
        You've successfully enabled Two-Factor Authentication. Here are your backup codes:
        
        {codes_text}
        
        IMPORTANT:
        • Each code can only be used once
        • Store these codes in a safe place
        • Use these if you lose access to your authenticator app
        • Generate new codes if these are compromised
        
        Keep this email secure - it contains sensitive information.
        
        © 2024 YetAI Sports Betting Platform
        """

        return self.send_email(to_email, subject, html_body, text_body)


# Service instance
email_service = EmailService()
