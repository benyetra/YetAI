"""
AI Chat Service for Sports Betting Assistant
Provides intelligent chat responses using OpenAI and real sports data
"""

import asyncio
import json
from typing import List, Dict, Any, Optional
from datetime import datetime
import random
from app.core.config import settings
from app.services.data_pipeline import sports_pipeline
from app.services.fantasy_pipeline import fantasy_pipeline


# Mock OpenAI client for development (replace with real OpenAI when API key is available)
class MockOpenAIClient:
    async def chat_completions_create(
        self, messages: List[Dict], model: str = "gpt-3.5-turbo"
    ):
        # Simulate AI response based on user input
        user_message = messages[-1]["content"].lower()

        if any(
            word in user_message
            for word in ["odds", "bet", "line", "spread", "moneyline"]
        ):
            return {
                "choices": [
                    {
                        "message": {
                            "content": "Based on current odds data, I can see several interesting betting opportunities. The Chiefs are favored by 3.5 points against the Chargers, which looks like good value given their recent performance. Would you like me to analyze specific matchups or betting lines?"
                        }
                    }
                ]
            }
        elif any(
            word in user_message
            for word in ["fantasy", "start", "sit", "lineup", "player"]
        ):
            return {
                "choices": [
                    {
                        "message": {
                            "content": "For fantasy this week, I'm seeing strong projections for Josh Allen and Patrick Mahomes at QB. Nick Chubb has an elite matchup at RB. Would you like position-specific start/sit advice or help with your lineup decisions?"
                        }
                    }
                ]
            }
        elif any(
            word in user_message for word in ["game", "schedule", "matchup", "team"]
        ):
            return {
                "choices": [
                    {
                        "message": {
                            "content": "Looking at this week's NFL schedule, there are some exciting matchups. The Chiefs vs Seahawks game should be high-scoring, while the Eagles vs Cowboys rivalry always brings intensity. Which games are you most interested in?"
                        }
                    }
                ]
            }
        else:
            return {
                "choices": [
                    {
                        "message": {
                            "content": "I'm here to help with NFL betting insights, fantasy football advice, and game analysis. I have access to live odds, player projections, and game data. What would you like to know about?"
                        }
                    }
                ]
            }


class AIChatService:
    """AI-powered chat service for sports betting and fantasy advice"""

    def __init__(self):
        self.openai_client = None
        # Check if we have a valid OpenAI API key (not Anthropic or placeholder)
        self.has_openai = bool(
            settings.OPENAI_API_KEY
            and settings.OPENAI_API_KEY != "your_openai_api_key_here"
            and settings.OPENAI_API_KEY.startswith("sk-")
            and not settings.OPENAI_API_KEY.startswith("sk-ant-")
        )

        if self.has_openai:
            try:
                import openai

                self.openai_client = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
                print("Using real OpenAI client")
            except ImportError:
                print("OpenAI package not available, using mock responses")
                self.openai_client = MockOpenAIClient()
        else:
            print(
                "OpenAI API key not configured or invalid format, using mock responses"
            )
            self.openai_client = MockOpenAIClient()

    async def get_chat_response(
        self, user_message: str, conversation_history: List[Dict] = None
    ) -> Dict[str, Any]:
        """Generate AI response to user message with context"""
        try:
            # Get current context data
            context_data = await self.get_context_data()

            # Build system prompt with context
            system_prompt = self._build_system_prompt(context_data)

            # Prepare messages for AI
            messages = [{"role": "system", "content": system_prompt}]

            # Add conversation history
            if conversation_history:
                messages.extend(
                    conversation_history[-10:]
                )  # Keep last 10 messages for context

            # Add current user message
            messages.append({"role": "user", "content": user_message})

            # Get AI response
            if hasattr(self.openai_client, "chat") and hasattr(
                self.openai_client.chat, "completions"
            ):
                response = await self.openai_client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=messages,
                    max_tokens=500,
                    temperature=0.7,
                )
                ai_response = response.choices[0].message.content
            else:
                # Use mock client
                response = await self.openai_client.chat_completions_create(messages)
                ai_response = response["choices"][0]["message"]["content"]

            # Determine response type
            response_type = self._classify_response_type(user_message)

            return {
                "response": ai_response,
                "type": response_type,
                "timestamp": datetime.now().isoformat(),
                "context_used": {
                    "games_count": len(context_data.get("games", [])),
                    "odds_count": len(context_data.get("odds", [])),
                    "fantasy_projections": len(
                        context_data.get("fantasy_projections", [])
                    ),
                },
            }

        except Exception as e:
            print(f"Error in chat response: {e}")
            # Fallback response
            return {
                "response": "I'm sorry, I'm having trouble processing that request right now. Please try asking about NFL games, betting odds, or fantasy football advice.",
                "type": "error",
                "timestamp": datetime.now().isoformat(),
                "error": str(e),
            }

    async def get_context_data(self) -> Dict[str, Any]:
        """Fetch current context data for AI responses"""
        try:
            # Fetch data concurrently
            games_task = sports_pipeline.get_nfl_games_today()
            odds_task = sports_pipeline.get_nfl_odds()
            fantasy_task = fantasy_pipeline.get_nfl_players(limit=20)

            games, odds, players = await asyncio.gather(
                games_task, odds_task, fantasy_task, return_exceptions=True
            )

            # Generate fantasy projections
            fantasy_projections = []
            if not isinstance(players, Exception) and not isinstance(games, Exception):
                try:
                    fantasy_projections = fantasy_pipeline.generate_fantasy_projections(
                        players, games
                    )[:10]
                except Exception as e:
                    print(f"Error generating fantasy projections: {e}")

            return {
                "games": games if not isinstance(games, Exception) else [],
                "odds": odds if not isinstance(odds, Exception) else [],
                "fantasy_projections": fantasy_projections,
                "last_updated": datetime.now().isoformat(),
            }

        except Exception as e:
            print(f"Error fetching context data: {e}")
            return {"games": [], "odds": [], "fantasy_projections": [], "error": str(e)}

    def _build_system_prompt(self, context_data: Dict) -> str:
        """Build system prompt with current data context"""
        prompt = """You are an expert NFL sports betting and fantasy football assistant. You provide helpful, accurate advice based on current data.

Current Context:
"""

        # Add games context
        games = context_data.get("games", [])
        if games:
            prompt += f"\nUpcoming NFL Games ({len(games)} games):\n"
            for game in games[:5]:  # Top 5 games
                prompt += f"- {game.get('away_team', 'Away')} @ {game.get('home_team', 'Home')} ({game.get('status', 'Scheduled')})\n"

        # Add odds context
        odds = context_data.get("odds", [])
        if odds:
            prompt += f"\nCurrent Betting Odds ({len(odds)} games with odds):\n"
            for odd in odds[:3]:  # Top 3 odds
                home_ml = odd.get("moneyline", {}).get("home", "N/A")
                away_ml = odd.get("moneyline", {}).get("away", "N/A")
                prompt += f"- {odd.get('away_team', 'Away')} ({away_ml}) @ {odd.get('home_team', 'Home')} ({home_ml})\n"

        # Add fantasy context
        fantasy = context_data.get("fantasy_projections", [])
        if fantasy:
            prompt += f"\nTop Fantasy Projections ({len(fantasy)} players):\n"
            for player in fantasy[:5]:  # Top 5 players
                prompt += f"- {player.get('player_name', 'Unknown')} ({player.get('position', 'POS')}, {player.get('team', 'TEAM')}): {player.get('projected_points', 0)} pts\n"

        prompt += """
Guidelines:
- Provide specific, actionable advice based on the current data
- Always include disclaimers about responsible betting
- Be conversational but professional
- If asked about specific players/teams not in the data, acknowledge the limitation
- For fantasy advice, consider projections, matchups, and player health
- For betting advice, analyze odds value and game context
- Keep responses concise (under 200 words)

Remember: This is for entertainment purposes only. Always bet responsibly.
"""

        return prompt

    def _classify_response_type(self, user_message: str) -> str:
        """Classify the type of response needed"""
        message_lower = user_message.lower()

        if any(
            word in message_lower
            for word in ["bet", "odds", "line", "spread", "moneyline", "under", "over"]
        ):
            return "betting_advice"
        elif any(
            word in message_lower
            for word in ["fantasy", "start", "sit", "lineup", "player", "projection"]
        ):
            return "fantasy_advice"
        elif any(
            word in message_lower
            for word in ["game", "schedule", "matchup", "score", "team"]
        ):
            return "game_analysis"
        else:
            return "general"

    async def get_quick_suggestions(self) -> List[Dict[str, str]]:
        """Get quick suggestion prompts for users"""
        suggestions = [
            {
                "text": "What are the best bets for this week?",
                "category": "betting",
                "icon": "target",
            },
            {
                "text": "Who should I start at QB this week?",
                "category": "fantasy",
                "icon": "users",
            },
            {
                "text": "Which games have the best odds value?",
                "category": "betting",
                "icon": "trending-up",
            },
            {
                "text": "Give me your top fantasy sleepers",
                "category": "fantasy",
                "icon": "star",
            },
            {
                "text": "What's the over/under analysis for Chiefs game?",
                "category": "betting",
                "icon": "bar-chart",
            },
            {
                "text": "Should I start or sit Derrick Henry?",
                "category": "fantasy",
                "icon": "help-circle",
            },
        ]

        # Randomize and return 4 suggestions
        random.shuffle(suggestions)
        return suggestions[:4]


# Create global instance
ai_chat_service = AIChatService()
