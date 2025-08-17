#!/usr/bin/env python3
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'backend'))

import pyotp
from app.services.auth_service import auth_service

# Get the user to find their temp secret
user = auth_service.users[1]
print('Temp TOTP Secret:', user.get('temp_totp_secret'))

# Generate current token
if user.get('temp_totp_secret'):
    totp = pyotp.TOTP(user['temp_totp_secret'])
    current_token = totp.now()
    print('Current TOTP Token:', current_token)
else:
    print('No temp secret found - need to call setup first')