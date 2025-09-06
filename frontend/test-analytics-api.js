const fetch = require('node-fetch');

async function testAnalyticsAPI() {
  const API_BASE = 'http://localhost:8001';
  
  // First, test if we can search for any players
  try {
    console.log('🔍 Testing player search...');
    const searchResponse = await fetch(`${API_BASE}/api/fantasy/players/search?query=josh+allen`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json'
        // Note: We should add auth token but let's see if this works first
      }
    });
    
    const searchResult = await searchResponse.json();
    console.log('Search Response Status:', searchResponse.status);
    console.log('Search Result:', JSON.stringify(searchResult, null, 2));
    
    if (searchResult.players && searchResult.players.length > 0) {
      const samplePlayer = searchResult.players[0];
      console.log(`\n📊 Testing analytics for player: ${samplePlayer.name} (ID: ${samplePlayer.player_id})`);
      
      // Test analytics endpoint
      const analyticsResponse = await fetch(`${API_BASE}/api/fantasy/analytics/${samplePlayer.player_id}?weeks=8,9,10,11,12&season=2024`);
      const analyticsResult = await analyticsResponse.json();
      
      console.log('Analytics Response Status:', analyticsResponse.status);
      console.log('Analytics Result:', JSON.stringify(analyticsResult, null, 2));
      
      // Test trends endpoint
      const trendsResponse = await fetch(`${API_BASE}/api/fantasy/analytics/${samplePlayer.player_id}/trends?weeks=8,9,10,11,12&season=2024`);
      const trendsResult = await trendsResponse.json();
      
      console.log('Trends Response Status:', trendsResponse.status);
      console.log('Trends Result:', JSON.stringify(trendsResult, null, 2));
      
      // Test efficiency endpoint
      const efficiencyResponse = await fetch(`${API_BASE}/api/fantasy/analytics/${samplePlayer.player_id}/efficiency?weeks=8,9,10,11,12&season=2024`);
      const efficiencyResult = await efficiencyResponse.json();
      
      console.log('Efficiency Response Status:', efficiencyResponse.status);
      console.log('Efficiency Result:', JSON.stringify(efficiencyResult, null, 2));
    }
    
  } catch (error) {
    console.error('❌ Test failed:', error);
  }
}

testAnalyticsAPI().catch(console.error);