# Real Data Setup Guide

Your AI Sports Betting MVP is currently running with **mock data** for demonstration purposes. To enable **real live data**, you'll need to configure API keys for external data sources.

## Current Status
- ✅ **Mock Data**: Working (for demonstration)  
- ❌ **Real NFL Games**: Needs ESPN API or alternatives
- ❌ **Live Odds**: Needs Odds API key
- ❌ **AI Chat**: Needs OpenAI API key

## Setup Real Data Sources

### 1. Live Betting Odds
**Get The Odds API Key** (Recommended)
- Visit: https://the-odds-api.com/
- Sign up for free account (100 requests/month free)
- Get your API key
- Add to `.env`: `ODDS_API_KEY=your_actual_key_here`

### 2. AI Chat Assistant
**Get OpenAI API Key**
- Visit: https://platform.openai.com/api-keys
- Create account and get API key
- Add to `.env`: `OPENAI_API_KEY=sk-your_actual_key_here`

### 3. Weather Data (Optional)
**Get OpenWeatherMap API Key**
- Visit: https://openweathermap.org/api
- Sign up for free account
- Add to `.env`: `WEATHER_API_KEY=your_actual_key_here`

## Configuration Steps

1. **Edit the .env file** in the `/backend` directory:
   ```bash
   # Replace 'your_odds_api_key_here' with your actual key
   ODDS_API_KEY=your_actual_odds_api_key
   OPENAI_API_KEY=sk-your_actual_openai_key
   WEATHER_API_KEY=your_actual_weather_key
   ```

2. **Restart the backend server**:
   ```bash
   cd backend
   # Kill the current server (Ctrl+C)
   # Restart with new config
   source venv/bin/activate
   python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```

## What You'll Get With Real Data

### Real Live Odds ⚡
- Current betting lines from major sportsbooks
- Moneyline, spread, and totals
- Real-time updates throughout the day

### AI Chat Assistant 🤖  
- Personalized betting advice
- Fantasy football recommendations
- Game analysis and predictions
- Conversational sports insights

### Enhanced Fantasy Data 🏈
- Real player statistics
- Live injury reports  
- Weather impact analysis
- Advanced projection algorithms

## Current Mock Data Features
Even without API keys, you can explore:
- ✅ **Performance Analytics** - Track prediction accuracy
- ✅ **Fantasy Projections** - Mock player data and projections  
- ✅ **Interactive Dashboard** - Full UI functionality
- ✅ **7 Enhanced Endpoints** - All API endpoints working with mock data

## Cost Information
- **The Odds API**: Free tier (100 requests/month), paid plans from $10/month
- **OpenAI API**: Pay-per-use, typically $0.01-0.03 per request
- **Weather API**: Free tier available, very low cost
- **Total Monthly Cost**: Typically under $20/month for moderate usage

## Need Help?
If you need assistance setting up real data sources:
1. Check the API documentation links above
2. Verify your API keys are active and have proper permissions
3. Monitor the backend logs for connection errors
4. Test individual endpoints with curl to debug issues

Once configured, restart the application and you'll see real live data! 🚀