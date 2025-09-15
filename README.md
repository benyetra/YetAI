# AI Sports Betting MVP

AI-powered sports betting and fantasy football platform with real-time data integration

## Quick Start

### 1. Setup Database
```bash
cd database
./setup_db.sh
```

### 2. Start Development Environment
```bash
cd scripts
./start_dev.sh
```

### 3. Test Setup
Visit http://localhost:3000 and click "Test API Connection"

## URLs
- **Frontend**: http://localhost:3000
- **Backend API**: http://localhost:8000
- **API Documentation**: http://localhost:8000/docs

## Environment Structure
```
ai-sports-betting-mvp/
├── backend/           # FastAPI Python backend
├── frontend/          # Next.js TypeScript frontend
├── database/          # PostgreSQL schema and scripts
├── scripts/           # Development and deployment scripts
└── docs/             # Documentation
```

## Configuration

### Backend Environment (.env)
Copy `backend/.env` and add your API keys:
- `ODDS_API_KEY`: From the-odds-api.com
- `OPENAI_API_KEY`: From openai.com

### Services Required
- PostgreSQL (localhost:5432)
- Redis (localhost:6379)

## Development Workflow

1. **Backend changes**: Auto-reloads with uvicorn
2. **Frontend changes**: Auto-reloads with Next.js
3. **Database changes**: Run migrations in `/database`

## Testing

- **API Tests**: Visit http://localhost:3000 and click "Test API Connection"
- **Full Stack**: Check both frontend and backend are running

## Troubleshooting

### PostgreSQL Issues
```bash
# Start PostgreSQL
brew services start postgresql  # macOS
sudo systemctl start postgresql # Linux

# Check status
pg_isready
```

### Redis Issues
```bash
# Start Redis
brew services start redis       # macOS
sudo systemctl start redis      # Linux

# Test connection
redis-cli ping
```

### Port Conflicts
- Backend runs on port 8000
- Frontend runs on port 3000
- Change ports in start script if needed

## Next Steps

1. Add your API keys to `backend/.env`
2. Test the connection at http://localhost:3000
3. Start building features!# Testing pipelines after reset
