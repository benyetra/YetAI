#!/bin/bash
# YetAI Sports Betting MVP - Production Deployment Script
# Run this script to deploy to production after authentication

set -e  # Exit on any error

echo "🚀 YetAI Sports Betting MVP - Production Deployment"
echo "=================================================="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if we're in the right directory
if [[ ! -f "DEPLOYMENT.md" ]]; then
    print_error "Please run this script from the project root directory"
    exit 1
fi

print_status "Checking prerequisites..."

# Check if Railway CLI is installed and authenticated
if ! command -v railway &> /dev/null; then
    print_error "Railway CLI is not installed. Please run: npm install -g @railway/cli"
    exit 1
fi

# Check if Vercel CLI is installed and authenticated  
if ! command -v vercel &> /dev/null; then
    print_error "Vercel CLI is not installed. Please run: npm install -g vercel"
    exit 1
fi

print_status "CLIs are installed. Checking authentication..."

# Check Railway auth
if ! railway whoami &> /dev/null; then
    print_warning "Not logged in to Railway. Please run: railway login"
    print_status "This will open a browser for authentication."
    print_status "After authentication, re-run this script."
    exit 1
fi

# Check Vercel auth
if ! vercel whoami &> /dev/null; then
    print_warning "Not logged in to Vercel. Please run: vercel login"
    print_status "After authentication, re-run this script."
    exit 1
fi

print_success "Authentication verified!"

# Deploy Backend to Railway
print_status "Deploying backend to Railway..."
cd backend/

# Initialize Railway project if needed
if [[ ! -d ".railway" ]]; then
    print_status "Initializing new Railway project..."
    railway init --name yetai-backend
fi

# Add PostgreSQL database if it doesn't exist
print_status "Adding PostgreSQL database..."
railway add --database postgres || print_warning "Database might already exist"

# Deploy the backend
print_status "Building and deploying backend..."
railway up

# Get the deployment URL
print_status "Getting deployment URL..."
BACKEND_URL=$(railway status 2>/dev/null | grep -E "https?://" | head -1 | awk '{print $2}')
if [[ -z "$BACKEND_URL" ]]; then
    print_warning "Could not automatically detect Railway URL. Please check Railway dashboard."
    BACKEND_URL="https://your-railway-url.railway.app"
fi

print_success "Backend deployed to: $BACKEND_URL"

cd ../

# Deploy Frontend to Vercel
print_status "Deploying frontend to Vercel..."
cd frontend/

# Set environment variables for Vercel
print_status "Configuring frontend environment variables..."
vercel env add NEXT_PUBLIC_API_URL production <<< "$BACKEND_URL" || print_warning "Environment variable might already exist"
vercel env add NEXT_PUBLIC_APP_URL production <<< "https://yetai.app" || print_warning "Environment variable might already exist"
vercel env add NODE_ENV production <<< "production" || print_warning "Environment variable might already exist"

# Deploy to Vercel
print_status "Building and deploying frontend..."
vercel --prod --yes

FRONTEND_URL=$(vercel ls | grep "frontend" | head -1 | awk '{print $2}')
print_success "Frontend deployed to: https://$FRONTEND_URL"

cd ../

# Final steps
print_success "🎉 Deployment Complete!"
echo ""
echo "Your YetAI Sports Betting MVP is now live:"
echo "  Backend API: $BACKEND_URL"
echo "  Frontend: https://$FRONTEND_URL"
echo ""
print_status "Next steps:"
echo "  1. Configure custom domains:"
echo "     - Railway: Set api.yetai.app to point to $BACKEND_URL"
echo "     - Vercel: Set yetai.app to point to your Vercel deployment"
echo "  2. Update environment variables with production secrets"
echo "  3. Test the deployment"
echo ""
print_status "Health checks:"
echo "  Backend: curl $BACKEND_URL/health"
echo "  Frontend: curl https://$FRONTEND_URL"
echo ""
print_success "Deployment documentation: DEPLOYMENT.md"