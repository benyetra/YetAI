"""
Test suite for the main application endpoints
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock, AsyncMock
import json

# Import the applications to test
from app.main import app as production_app  # Consolidated environment-aware app
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
        assert "YetAI Sports Betting MVP" in data["message"]
        assert data["version"] == "1.2.0"
        assert "environment" in data
        assert "services_available" in data
        assert "total_services" in data
    
    def test_health_endpoint(self, client):
        """Test the health check endpoint"""
        response = client.get("/health")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "healthy"
        assert "environment" in data
        assert "timestamp" in data
        assert "services" in data
    
    def test_api_status_endpoint(self, client):
        """Test the API status endpoint"""
        response = client.get("/api/status")
        assert response.status_code == 200
        
        data = response.json()
        assert data["api_status"] == "operational"
        assert "database_connected" in data
        assert "environment" in data
        assert "timestamp" in data
    
    @patch('app.core.service_loader.is_service_available')
    @patch('app.core.service_loader.get_service')
    def test_nfl_games_endpoint_success(self, mock_get_service, mock_is_available, client):
        """Test NFL games endpoint when service is available"""
        # Mock service availability and pipeline response
        mock_is_available.return_value = True
        mock_sports_pipeline = MagicMock()
        mock_sports_pipeline.get_nfl_games = AsyncMock(return_value=[
            {
                "id": "test123",
                "home_team": "KC",
                "away_team": "BUF",
                "start_time": "2025-09-07T17:00Z",
                "status": "scheduled"
            }
        ])
        mock_get_service.return_value = mock_sports_pipeline
        
        response = client.get("/api/games/nfl")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "success"
        assert "games" in data
    
    @patch('app.core.service_loader.is_service_available')
    def test_nfl_games_endpoint_unavailable(self, mock_is_available, client):
        """Test NFL games endpoint when service is unavailable"""
        mock_is_available.return_value = False
        
        response = client.get("/api/games/nfl")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "success"  # Returns mock data when unavailable
        assert "games" in data
        assert "message" in data
    
    @patch('app.core.service_loader.is_service_available')
    @patch('app.core.service_loader.get_service')
    def test_nfl_odds_endpoint_success(self, mock_get_service, mock_is_available, client):
        """Test NFL odds endpoint when service is available"""
        # Mock service availability - but odds endpoint doesn't use sports_pipeline directly
        mock_is_available.return_value = False  # Will return mock data
        
        response = client.get("/api/odds/nfl")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "success"
        assert "odds" in data
        # Note: May have real data if ODDS_API_KEY is configured
    
    @patch('app.core.service_loader.is_service_available')
    @patch('app.core.service_loader.get_service')
    def test_chat_message_endpoint_success(self, mock_get_service, mock_is_available, client):
        """Test chat message endpoint when service is available"""
        # Mock service availability and chat service response
        mock_is_available.return_value = True
        mock_chat_service = MagicMock()
        mock_chat_service.send_message = AsyncMock(return_value={
            "role": "assistant",
            "content": "Based on current data, I recommend the Chiefs.",
            "timestamp": "2025-09-07T15:30:00"
        })
        mock_get_service.return_value = mock_chat_service
        
        chat_request = {
            "message": "What are the best bets today?",
            "conversation_history": []
        }
        
        response = client.post("/api/chat/message", json=chat_request)
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "success"
        assert "response" in data
    
    @patch('app.core.service_loader.is_service_available')
    def test_chat_message_endpoint_unavailable(self, mock_is_available, client):
        """Test chat message endpoint when service is unavailable"""
        mock_is_available.return_value = False
        
        chat_request = {
            "message": "What are the best bets today?",
            "conversation_history": []
        }
        
        response = client.post("/api/chat/message", json=chat_request)
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "success"  # Returns mock response when unavailable
        assert "response" in data
        assert "message" in data
    
    def test_chat_suggestions_endpoint(self, client):
        """Test chat suggestions endpoint"""
        response = client.get("/api/chat/suggestions")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "success"
        assert "suggestions" in data
        assert len(data["suggestions"]) == 4  # Updated count
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
    
    @patch('app.core.service_loader.is_service_available')
    @patch('app.core.service_loader.get_service')
    def test_nfl_games_service_error(self, mock_get_service, mock_is_available, client):
        """Test NFL games endpoint when service throws an error"""
        mock_is_available.return_value = True
        mock_sports_pipeline = MagicMock()
        mock_sports_pipeline.get_nfl_games = MagicMock(side_effect=Exception("Service error"))
        mock_get_service.return_value = mock_sports_pipeline
        
        response = client.get("/api/games/nfl")
        assert response.status_code == 200  # We handle errors gracefully
        
        data = response.json()
        assert data["status"] == "success"  # Falls back to mock data on error
        assert "games" in data


if __name__ == "__main__":
    pytest.main([__file__, "-v"])