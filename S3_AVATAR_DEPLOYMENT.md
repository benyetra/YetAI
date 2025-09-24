# YetAI S3 Avatar Storage - Complete Deployment Guide

## ✅ Changes Made

### 1. Enhanced Avatar Service (`app/services/avatar_service.py`)
- ✅ Added S3 support with boto3 integration
- ✅ Automatic fallback to local storage if S3 not configured
- ✅ Smart bucket name parsing (handles `s3://bucket/path` format)
- ✅ Region-specific URL generation (us-east-2 compatible)
- ✅ Comprehensive logging and error handling
- ✅ Public read permissions with long-term caching
- ✅ Metadata tracking (user ID, upload time)

### 2. Updated Dependencies
- ✅ Added `boto3==1.34.162` to `requirements.txt`

### 3. Created Setup Scripts
- ✅ `scripts/setup_s3_bucket.py` - Configure bucket permissions
- ✅ `install_s3_deps.sh` - Install dependencies
- ✅ `test_avatar_service.py` - Test S3 integration

## 🚀 Deployment Steps

### Step 1: Set Environment Variables on Railway
```bash
AWS_ACCESS_KEY_ID=your_aws_access_key_id
AWS_SECRET_ACCESS_KEY=your_aws_secret_access_key
AWS_REGION=us-east-2
AWS_S3_BUCKET_NAME=yetai
```

### Step 2: Configure S3 Bucket Permissions

Run the setup script (locally with your AWS credentials):
```bash
cd backend
export AWS_ACCESS_KEY_ID=your_aws_access_key_id
export AWS_SECRET_ACCESS_KEY=your_aws_secret_access_key
python scripts/setup_s3_bucket.py
```

This will:
- ✅ Set up CORS for web uploads
- ✅ Configure public read access for `/avatars/*`
- ✅ Enable versioning
- ✅ Test upload/download functionality

### Step 3: Deploy to Railway

The deployment will automatically:
- ✅ Install boto3 dependency
- ✅ Detect S3 configuration via environment variables
- ✅ Log "Using S3 for avatar storage" on startup
- ✅ Store all new avatars in S3

## 🧪 Testing

### Local Testing
```bash
cd backend
python test_avatar_service.py
```

### Production Testing
1. Upload an avatar through the frontend
2. Check Railway logs for S3 upload confirmations:
   ```
   INFO: Using S3 for avatar storage
   INFO: S3 initialized with bucket: yetai in region: us-east-2
   INFO: Uploading avatar to S3: avatars/10_abc123def.jpg
   INFO: ✅ Successfully uploaded avatar for user 10
   ```
3. Verify avatar persists across deployments

## 📁 File Structure After Deployment

**S3 Bucket Structure:**
```
s3://yetai/
├── avatars/
│   ├── 10_abc123def.jpg        (main avatar)
│   ├── 10_thumb_xyz789.jpg     (thumbnail)
│   ├── 15_def456ghi.jpg
│   └── ...
```

**Generated URLs:**
```
https://yetai.s3.us-east-2.amazonaws.com/avatars/10_abc123def.jpg
```

## 🔧 How It Works

### Storage Decision Logic
```python
if AWS credentials configured:
    use S3 storage  # ✅ Persistent across deployments
else:
    use local storage  # ⚠️ Lost on deployment (fallback)
```

### Upload Process
1. **Image Processing**: Resize, convert to JPEG, create thumbnail
2. **S3 Upload**: Upload both files with public-read ACL
3. **URL Generation**: Return full S3 HTTPS URLs
4. **Database**: Store S3 URLs in user profile

### Benefits
- 🚀 **Persistent**: Files survive deployments and restarts
- ⚡ **Fast**: Direct S3 access with 1-year caching
- 💾 **Scalable**: No local storage limitations
- 🔄 **Backwards Compatible**: Existing local URLs still work
- 📊 **Trackable**: Metadata for debugging and analytics

## 🚨 Troubleshooting

### Avatar Still 404ing
1. Check Railway environment variables are set correctly
2. Look for S3 initialization logs: `Using S3 for avatar storage`
3. Verify bucket permissions with setup script
4. Test S3 access manually

### Local Storage Fallback
If you see: `Using local storage for avatars (files will be lost on deployment)`
- Check AWS environment variables are set
- Verify boto3 is installed
- Run the test script for detailed error info

## ✅ Final Checklist

- [ ] Environment variables set on Railway
- [ ] S3 bucket configured with setup script
- [ ] Deployed to Railway
- [ ] Tested avatar upload
- [ ] Verified persistence across deployments
- [ ] Checked logs for S3 confirmation

**The avatar 404 issue will be completely resolved once deployed with S3! 🎉**