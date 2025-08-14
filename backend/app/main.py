from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import asyncio
import logging
from datetime import datetime

from app.services.data_pipeline import sports_pipeline
from app.services.fantasy_pipeline import fantasy_pipeline
from app.services.ai_chat_service import ai_chat_service
from app.services.real_fantasy_pipeline import real_fantasy_pipeline
from app.services.performance_tracker import performance_tracker
from app.core.config import settings
from pydantic import BaseModel
from typing import List, Optional

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Chat Models
class ChatMessage(BaseModel):
    role: str
    content: str
    timestamp: Optional[str] = None

class ChatRequest(BaseModel):
    message: str
    conversation_history: Optional[List[ChatMessage]] = None

app = FastAPI(
    title="AI Sports Betting MVP",
    description="AI-powered sports betting and fantasy insights platform",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {
        "message": "AI Sports Betting MVP API",
        "version": "0.1.0",
        "status": "running"
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

# Test endpoints for development
@app.get("/test/odds")
async def test_odds():
    # Mock odds data for testing
    return {
        "game": "Team A vs Team B",
        "odds": {
            "moneyline": {"home": -110, "away": +120},
            "spread": {"line": -3.5, "odds": -110}
        },
        "recommendation": "Value bet on away team moneyline"
    }

@app.get("/test/fantasy")
async def test_fantasy():
    # Mock fantasy data
    return {
        "player": "John Doe",
        "position": "QB",
        "projected_points": 24.5,
        "recommendation": "Strong start this week"
    }

# Real API endpoints
@app.get("/api/games/nfl")
async def get_nfl_games():
    """Get current NFL games"""
    try:
        games = await sports_pipeline.get_nfl_games_today()
        return {
            "status": "success",
            "count": len(games),
            "games": games
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching games: {str(e)}")

@app.get("/api/odds/nfl")
async def get_nfl_odds():
    """Get current NFL betting odds"""
    try:
        odds = await sports_pipeline.get_nfl_odds()
        return {
            "status": "success",
            "count": len(odds),
            "odds": odds
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching odds: {str(e)}")

@app.get("/api/predictions/daily")
async def get_daily_predictions():
    """Get today's AI betting predictions"""
    try:
        # Fetch both games and odds
        games_task = sports_pipeline.get_nfl_games_today()
        odds_task = sports_pipeline.get_nfl_odds()
        
        games, odds = await asyncio.gather(games_task, odds_task)
        
        # Generate predictions
        predictions = sports_pipeline.generate_simple_predictions(games, odds)
        
        return {
            "status": "success",
            "date": datetime.now().strftime("%Y-%m-%d"),
            "count": len(predictions),
            "predictions": predictions,
            "disclaimer": "For entertainment purposes only. Bet responsibly."
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating predictions: {str(e)}")

@app.get("/api/data/status")
async def get_data_status():
    """Check status of all data sources"""
    status = {
        "espn_api": "unknown",
        "odds_api": "unknown",
        "last_updated": None
    }
    
    try:
        # Test ESPN API
        games = await sports_pipeline.get_nfl_games_today()
        status["espn_api"] = "connected" if games else "no_data"
        
        # Test Odds API
        odds = await sports_pipeline.get_nfl_odds()
        status["odds_api"] = "connected" if odds else "no_key_or_error"
        
        status["last_updated"] = datetime.now().isoformat()
        
    except Exception as e:
        status["error"] = str(e)
    
    return status

# Fantasy API endpoints
@app.get("/api/fantasy/projections")
async def get_fantasy_projections():
    """Get weekly fantasy point projections for all players"""
    try:
        players_task = fantasy_pipeline.get_nfl_players(limit=100)
        games_task = sports_pipeline.get_nfl_games_today()
        
        players, games = await asyncio.gather(players_task, games_task)
        projections = fantasy_pipeline.generate_fantasy_projections(players, games)
        
        return {
            "status": "success",
            "week": "Current Week",
            "count": len(projections),
            "projections": projections,
            "last_updated": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating projections: {str(e)}")

@app.get("/api/fantasy/start-sit/{position}")
async def get_start_sit_advice(position: str):
    """Get start/sit advice for specific position"""
    try:
        valid_positions = ['QB', 'RB', 'WR', 'TE', 'K']
        if position.upper() not in valid_positions:
            raise HTTPException(status_code=400, detail=f"Invalid position. Must be one of: {valid_positions}")
        
        players = await fantasy_pipeline.get_nfl_players(limit=200)
        games = await sports_pipeline.get_nfl_games_today()
        projections = fantasy_pipeline.generate_fantasy_projections(players, games)
        advice = fantasy_pipeline.get_start_sit_advice(projections, position.upper())
        
        return {
            "status": "success",
            "position": position.upper(),
            "count": len(advice),
            "advice": advice,
            "last_updated": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting start/sit advice: {str(e)}")

# AI Chat endpoints
@app.post("/api/chat/message")
async def send_chat_message(request: ChatRequest):
    """Send a message to the AI chat assistant"""
    try:
        history = []
        if request.conversation_history:
            for msg in request.conversation_history:
                history.append({"role": msg.role, "content": msg.content})
        
        response = await ai_chat_service.get_chat_response(request.message, history)
        
        return {
            "status": "success",
            "message": response["response"],
            "type": response["type"],
            "timestamp": response.get("timestamp"),
            "context_used": response.get("context_used", {}),
            "disclaimer": "For entertainment purposes only. Please bet responsibly."
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing chat message: {str(e)}")

@app.get("/api/chat/suggestions")
async def get_chat_suggestions():
    """Get quick suggestion prompts for the chat"""
    try:
        suggestions = await ai_chat_service.get_quick_suggestions()
        return {"status": "success", "suggestions": suggestions, "count": len(suggestions)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting suggestions: {str(e)}")

@app.get("/api/chat/health")
async def check_chat_health():
    """Check if AI chat services are working"""
    health_status = {
        "openai_configured": bool(settings.OPENAI_API_KEY),
        "data_sources": {"games_api": False, "odds_api": False, "fantasy_api": False},
        "status": "unknown"
    }
    
    try:
        context_data = await ai_chat_service.get_context_data()
        health_status["data_sources"]["games_api"] = len(context_data.get("games", [])) > 0
        health_status["data_sources"]["odds_api"] = len(context_data.get("odds", [])) > 0
        health_status["data_sources"]["fantasy_api"] = len(context_data.get("fantasy_projections", [])) > 0
        
        if health_status["openai_configured"] and any(health_status["data_sources"].values()):
            health_status["status"] = "healthy"
        elif health_status["openai_configured"]:
            health_status["status"] = "limited"
        else:
            health_status["status"] = "degraded"
    except Exception as e:
        health_status["status"] = "error"
        health_status["error"] = str(e)
    
    return health_status

# Enhanced Fantasy API endpoints
@app.get("/api/fantasy/projections/v2")
async def get_enhanced_fantasy_projections():
    """Get enhanced fantasy projections using real player stats"""
    try:
        # Get real player stats
        logger.info("Fetching real player season stats...")
        player_stats = await real_fantasy_pipeline.get_player_season_stats()
        
        # Get games for context
        games = await sports_pipeline.get_nfl_games_today()
        
        # Get injury reports
        injury_data = await real_fantasy_pipeline.get_injury_reports()
        
        # Get weather data
        weather_data = await real_fantasy_pipeline.get_weather_data(games)
        
        # Generate advanced projections
        projections = real_fantasy_pipeline.calculate_advanced_projections(
            player_stats, games, injury_data, weather_data
        )
        
        # Record predictions for tracking (async)
        for projection in projections[:10]:  # Track top 10 projections
            asyncio.create_task(performance_tracker.record_prediction({
                'type': 'fantasy',
                'player_id': projection['player_id'],
                'name': projection['name'],
                'team': projection['team'],
                'position': projection['position'],
                'opponent': projection['opponent'],
                'predicted_points': projection['projected_points'],
                'confidence': projection['confidence'],
                'reasoning': projection['reasoning'],
                'game_date': projection['game_date']
            }))
        
        return {
            "status": "success",
            "version": "2.0",
            "data_sources": {
                "player_stats": len(player_stats),
                "injury_reports": len(injury_data),
                "weather_data": len(weather_data),
                "games": len(games)
            },
            "projections": projections,
            "last_updated": datetime.now().isoformat(),
            "methodology": "Real season stats + injury reports + weather + matchup analysis"
        }
        
    except Exception as e:
        logger.error(f"Error generating enhanced projections: {e}")
        raise HTTPException(status_code=500, detail=f"Error generating projections: {str(e)}")

@app.get("/api/fantasy/player-stats/{player_id}")
async def get_detailed_player_stats(player_id: str):
    """Get detailed season stats for a specific player"""
    try:
        # Get all player stats
        all_stats = await real_fantasy_pipeline.get_player_season_stats()
        
        if player_id not in all_stats:
            raise HTTPException(status_code=404, detail="Player not found")
        
        player_data = all_stats[player_id]
        
        # Calculate per-game averages
        games_played = player_data['stats'].get('games_played', 1)
        per_game_stats = {}
        
        for stat_name, value in player_data['stats'].items():
            if stat_name != 'games_played' and isinstance(value, (int, float)):
                per_game_stats[f"{stat_name}_per_game"] = round(value / games_played, 2)
        
        return {
            "status": "success",
            "player": {
                "id": player_id,
                "name": player_data['name'],
                "position": player_data['position'],
                "team": player_data['team'],
                "age": player_data.get('age'),
                "season_stats": player_data['stats'],
                "per_game_averages": per_game_stats,
                "games_played": games_played
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching player stats: {str(e)}")

@app.get("/api/performance/metrics")
async def get_prediction_performance():
    """Get prediction accuracy and performance metrics"""
    try:
        metrics = await performance_tracker.get_performance_metrics(days=30)
        return {
            "status": "success",
            "metrics": metrics
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching performance metrics: {str(e)}")

@app.get("/api/performance/best-predictions")
async def get_best_predictions():
    """Get the most accurate recent predictions"""
    try:
        best_preds = await performance_tracker.get_best_predictions(limit=15)
        return {
            "status": "success",
            "best_predictions": best_preds,
            "count": len(best_preds)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching best predictions: {str(e)}")

@app.post("/api/performance/simulate-data")
async def simulate_historical_performance():
    """Generate sample historical performance data for demo"""
    try:
        await performance_tracker.simulate_historical_data()
        return {
            "status": "success", 
            "message": "Sample historical data generated"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating sample data: {str(e)}")

@app.get("/api/fantasy/injury-report")
async def get_current_injury_report():
    """Get current injury reports for fantasy-relevant players"""
    try:
        injury_data = await real_fantasy_pipeline.get_injury_reports()
        
        # Format for frontend
        formatted_injuries = []
        for player_key, status in injury_data.items():
            formatted_injuries.append({
                "player": player_key.replace('_', ' ').title(),
                "status": status,
                "severity": "high" if status == "out" else "medium" if status in ["doubtful", "questionable"] else "low"
            })
        
        return {
            "status": "success",
            "injury_report": formatted_injuries,
            "last_updated": datetime.now().isoformat(),
            "total_players": len(formatted_injuries)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching injury report: {str(e)}")

@app.get("/api/fantasy/weather-impact")
async def get_weather_impact():
    """Get weather impact analysis for upcoming games"""
    try:
        games = await sports_pipeline.get_nfl_games_today()
        weather_data = await real_fantasy_pipeline.get_weather_data(games)
        
        # Format weather impact
        weather_impact = []
        for game_key, weather in weather_data.items():
            teams = game_key.split('_vs_')
            weather_impact.append({
                "matchup": f"{teams[0]} vs {teams[1]}",
                "conditions": weather['conditions'],
                "temperature": weather['temperature'],
                "wind_speed": weather['wind_speed'],
                "impact_rating": weather['impact_rating'],
                "fantasy_advice": {
                    "passing": "reduced" if weather['impact_rating'] == "high" else "normal",
                    "kicking": "difficult" if weather['wind_speed'] > 15 else "normal",
                    "running": "enhanced" if weather['impact_rating'] == "high" else "normal"
                }
            })
        
        return {
            "status": "success",
            "weather_impact": weather_impact,
            "games_analyzed": len(weather_impact)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching weather impact: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)