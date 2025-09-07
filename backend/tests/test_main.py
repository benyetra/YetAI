"""
Test suite for the main application endpoints
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock, AsyncMock
import json

# Import the applications to test
from production_main import app as production_app
from simple_main import app as simple_app


class TestProductionApp:
    """Test the production FastAPI application"""
    
    @pytest.fixture
    def client(self):
        return TestClient(production_app)
    
    def test_root_endpoint(self, client):
        """Test the root endpoint returns correct information"""
        response = client.get("/")
        assert response.status_code == 200
        
        data = response.json()
        assert data["message"] == "YetAI Sports Betting MVP API - Production"
        assert data["version"] == "1.2.0"
        assert data["status"] == "running"
        assert "database_available" in data
        assert "services" in data
        assert "timestamp" in data
    
    def test_health_endpoint(self, client):
        """Test the health check endpoint"""
        response = client.get("/health")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "healthy"
        assert "database" in data
        assert "timestamp" in data
        assert "services" in data
    
    def test_api_status_endpoint(self, client):
        """Test the API status endpoint"""
        response = client.get("/api/status")
        assert response.status_code == 200
        
        data = response.json()
        assert data["api_status"] == "online"
        assert "database_status" in data
        assert "features" in data
        assert "timestamp" in data
    
    @patch('production_main.SPORTS_PIPELINE_AVAILABLE', True)
    @patch('production_main.sports_pipeline')
    def test_nfl_games_endpoint_success(self, mock_pipeline, client):
        """Test NFL games endpoint when service is available"""
        # Mock the sports pipeline response
        mock_games = [
            {
                "id": "test123",
                "home_team": "KC",
                "away_team": "BUF",
                "date": "2025-09-07T17:00Z"
            }
        ]
        mock_pipeline.get_nfl_games_today = AsyncMock(return_value=mock_games)
        
        response = client.get("/api/games/nfl")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "success"
        assert data["count"] == 1
        assert data["games"] == mock_games
    
    @patch('production_main.SPORTS_PIPELINE_AVAILABLE', False)
    def test_nfl_games_endpoint_unavailable(self, client):
        """Test NFL games endpoint when service is unavailable"""
        response = client.get("/api/games/nfl")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "error"
        assert data["message"] == "Sports pipeline not available - service starting up"
        assert data["count"] == 0
        assert data["games"] == []
    
    @patch('production_main.SPORTS_PIPELINE_AVAILABLE', True)
    @patch('production_main.sports_pipeline')
    def test_nfl_odds_endpoint_success(self, mock_pipeline, client):
        """Test NFL odds endpoint when service is available"""
        # Mock the sports pipeline response
        mock_odds = [
            {
                "game_id": "test123",
                "home_team": "Kansas City Chiefs",
                "away_team": "Buffalo Bills",
                "bookmakers": []
            }
        ]
        mock_pipeline.get_nfl_odds = AsyncMock(return_value=mock_odds)
        
        response = client.get("/api/odds/nfl")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "success"
        assert data["count"] == 1
        assert data["odds"] == mock_odds
    
    @patch('production_main.AI_CHAT_SERVICE_AVAILABLE', True)
    @patch('production_main.ai_chat_service')
    def test_chat_message_endpoint_success(self, mock_chat_service, client):
        """Test chat message endpoint when service is available"""
        # Mock the AI chat service response
        mock_response = {
            "response": "Based on current data, I recommend the Chiefs.",
            "type": "betting_advice",
            "timestamp": "2025-09-07T15:30:00",
            "context_used": {"games_count": 16}
        }
        mock_chat_service.get_chat_response = AsyncMock(return_value=mock_response)
        
        chat_request = {
            "message": "What are the best bets today?",
            "conversation_history": []
        }
        
        response = client.post("/api/chat/message", json=chat_request)
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "success"
        assert data["message"] == mock_response["response"]
        assert data["type"] == "betting_advice"
        assert "disclaimer" in data
    
    @patch('production_main.AI_CHAT_SERVICE_AVAILABLE', False)
    def test_chat_message_endpoint_unavailable(self, client):
        """Test chat message endpoint when service is unavailable"""
        chat_request = {
            "message": "What are the best bets today?",
            "conversation_history": []
        }
        
        response = client.post("/api/chat/message", json=chat_request)
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "error"
        assert "unavailable" in data["message"]
        assert data["type"] == "error"
    
    def test_chat_suggestions_endpoint(self, client):
        """Test chat suggestions endpoint"""
        response = client.get("/api/chat/suggestions")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "success"
        assert "suggestions" in data
        assert len(data["suggestions"]) == 5
        assert all(isinstance(suggestion, str) for suggestion in data["suggestions"])


class TestSimpleApp:
    """Test the simple FastAPI application"""
    
    @pytest.fixture
    def client(self):
        return TestClient(simple_app)
    
    def test_root_endpoint(self, client):
        """Test the root endpoint returns correct information"""
        response = client.get("/")
        assert response.status_code == 200
        
        data = response.json()
        assert data["message"] == "YetAI Sports Betting MVP API"
        assert data["version"] == "1.0.0"
        assert data["status"] == "running"
        assert "timestamp" in data
    
    def test_health_endpoint(self, client):
        """Test the health check endpoint"""
        response = client.get("/health")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data
        assert "environment" in data
    
    def test_api_status_endpoint(self, client):
        """Test the API status endpoint"""
        response = client.get("/api/status")
        assert response.status_code == 200
        
        data = response.json()
        assert data["api_status"] == "online"
        assert data["database_status"] == "connected"
        assert "timestamp" in data


class TestHealthChecks:
    """Test health check functionality across apps"""
    
    @pytest.mark.parametrize("app_client", [
        TestClient(production_app),
        TestClient(simple_app)
    ])
    def test_health_endpoints_respond(self, app_client):
        """Test that all health endpoints respond correctly"""
        response = app_client.get("/health")
        assert response.status_code == 200
        
        data = response.json()
        assert "status" in data
        assert "timestamp" in data


class TestErrorHandling:
    """Test error handling across the applications"""
    
    @pytest.fixture
    def client(self):
        return TestClient(production_app)
    
    def test_invalid_endpoint(self, client):
        """Test accessing non-existent endpoint"""
        response = client.get("/nonexistent")
        assert response.status_code == 404
    
    def test_invalid_chat_request(self, client):
        """Test chat endpoint with invalid data"""
        response = client.post("/api/chat/message", json={})
        assert response.status_code == 422  # Validation error
    
    @patch('production_main.SPORTS_PIPELINE_AVAILABLE', True)
    @patch('production_main.sports_pipeline')
    def test_nfl_games_service_error(self, mock_pipeline, client):
        """Test NFL games endpoint when service throws an error"""
        mock_pipeline.get_nfl_games_today = MagicMock(side_effect=Exception("Service error"))
        
        response = client.get("/api/games/nfl")
        assert response.status_code == 200  # We handle errors gracefully
        
        data = response.json()
        assert data["status"] == "error"
        assert "Service error" in data["message"]
        assert data["count"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])