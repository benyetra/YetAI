/**
 * Test Team Name Fixes and Trade Analyzer Integration
 * Validates the Phase 4 fixes are working correctly
 */

const fetch = require('node-fetch');

async function testTeamNameFixes() {
  console.log('🚀 Testing Phase 4: Team Name Fixes and Trade Analyzer Integration\n');
  
  const API_BASE = 'http://localhost:8000';
  const results = {
    teamAnalysisTest: false,
    quickAnalysisTest: false,
    teamNamesFix: false,
    playerLookupFix: false
  };

  try {
    // Test 1: Team Analysis Endpoint
    console.log('📋 Test 1: Team Analysis Endpoint');
    console.log('   Testing: /api/v1/fantasy/trade-analyzer/team-analysis/1');
    
    const teamResponse = await fetch(`${API_BASE}/api/v1/fantasy/trade-analyzer/team-analysis/1`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json'
      }
    });
    
    if (teamResponse.ok) {
      const teamData = await teamResponse.json();
      console.log('✅ Team Analysis API responded successfully');
      console.log(`   Status: ${teamResponse.status}`);
      
      if (teamData.success && teamData.team_analysis && teamData.team_analysis.team_info) {
        const teamName = teamData.team_analysis.team_info.team_name;
        const ownerName = teamData.team_analysis.team_info.owner_name;
        
        console.log(`   Team Name: "${teamName}"`);
        console.log(`   Owner Name: "${ownerName}"`);
        
        // Check if we got real team names (not generic "Team X")
        if (teamName && !teamName.match(/^Team \d+$/)) {
          console.log('✅ TEAM NAME FIX WORKING: Real team name detected!');
          results.teamNamesFix = true;
        } else {
          console.log('⚠️  Still showing generic team name');
        }
        
        results.teamAnalysisTest = true;
      } else {
        console.log('⚠️  Invalid response structure');
      }
    } else {
      console.log(`❌ Team Analysis failed: ${teamResponse.status} ${teamResponse.statusText}`);
    }

    // Test 2: Quick Analysis Endpoint  
    console.log('\n📋 Test 2: Quick Trade Analysis Endpoint');
    console.log('   Testing: /api/v1/fantasy/trade-analyzer/quick-analysis');
    
    const quickAnalysisData = {
      team1_players: ["2449", "6786"], // Real player IDs from our database
      team2_players: ["7553", "5038"]
    };
    
    const quickResponse = await fetch(`${API_BASE}/api/v1/fantasy/trade-analyzer/quick-analysis`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(quickAnalysisData)
    });
    
    if (quickResponse.ok) {
      const quickData = await quickResponse.json();
      console.log('✅ Quick Analysis API responded successfully');
      console.log(`   Status: ${quickResponse.status}`);
      
      if (quickData.success && quickData.value_breakdown) {
        const team1Players = quickData.value_breakdown.team1_players || [];
        const team2Players = quickData.value_breakdown.team2_players || [];
        
        console.log(`   Team 1 Players Found: ${team1Players.length}`);
        console.log(`   Team 2 Players Found: ${team2Players.length}`);
        
        if (team1Players.length > 0) {
          console.log('✅ PLAYER LOOKUP FIX WORKING: team1_players populated!');
          console.log(`   Sample Player: ${team1Players[0].name} (${team1Players[0].position})`);
          results.playerLookupFix = true;
        } else {
          console.log('⚠️  team1_players still empty - player lookup issue');
        }
        
        results.quickAnalysisTest = true;
      } else {
        console.log('⚠️  Invalid quick analysis response structure');
      }
    } else {
      console.log(`❌ Quick Analysis failed: ${quickResponse.status} ${quickResponse.statusText}`);
    }

    // Test 3: Validate API Response Formats
    console.log('\n📋 Test 3: API Response Format Validation');
    
    if (results.teamAnalysisTest) {
      console.log('✅ Team Analysis Response Format: Valid');
    }
    
    if (results.quickAnalysisTest) {
      console.log('✅ Quick Analysis Response Format: Valid');
    }

  } catch (error) {
    console.error('❌ Test failed with error:', error.message);
  }

  // Summary
  console.log('\n📊 TEST SUMMARY:');
  console.log('================');
  console.log(`Team Analysis Endpoint: ${results.teamAnalysisTest ? '✅ PASS' : '❌ FAIL'}`);
  console.log(`Quick Analysis Endpoint: ${results.quickAnalysisTest ? '✅ PASS' : '❌ FAIL'}`);
  console.log(`Team Names Fix: ${results.teamNamesFix ? '✅ PASS' : '⚠️  PARTIAL'}`);
  console.log(`Player Lookup Fix: ${results.playerLookupFix ? '✅ PASS' : '⚠️  NEEDS CHECK'}`);
  
  const allPassed = Object.values(results).every(r => r === true);
  console.log(`\nOverall: ${allPassed ? '🎉 ALL TESTS PASS' : '⚠️  SOME ISSUES DETECTED'}`);
  
  return results;
}

// Run the test
if (require.main === module) {
  testTeamNameFixes().then(() => {
    console.log('\n🏁 Integration Test Complete!');
  }).catch(console.error);
}

module.exports = { testTeamNameFixes };