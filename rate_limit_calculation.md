# Rate Limiting Analysis - AI Sports Betting MVP

## Current Scheduler Configuration (Conservative Settings)

### Scheduled Tasks with New Intervals:

1. **Popular Odds Update**: Every 2 hours (7,200 seconds)
   - Sports covered: NFL, NBA, MLB, NHL (4 sports)
   - Requests per cycle: 4
   - Daily requests: 4 * (24/2) = 48
   - Monthly requests: 48 * 30 = 1,440

2. **Sports List Update**: Every 6 hours (21,600 seconds)
   - Requests per cycle: 1
   - Daily requests: 1 * (24/6) = 4
   - Monthly requests: 4 * 30 = 120

3. **Live Games Update**: Every 30 minutes (1,800 seconds)
   - Sports covered: 9 filtered sports
   - Requests per cycle: 9
   - Daily requests: 9 * (24 * 2) = 432
   - Monthly requests: 432 * 30 = 12,960

4. **Scores Update**: Every 4 hours (14,400 seconds)
   - Sports covered: NFL, NBA, MLB, NHL (4 sports)
   - Requests per cycle: 4
   - Daily requests: 4 * (24/4) = 24
   - Monthly requests: 24 * 30 = 720

### Total Estimated Monthly Usage:
- Popular odds: 1,440 requests
- Sports list: 120 requests
- Live games: 12,960 requests
- Scores: 720 requests
- **Total**: 15,240 requests/month

## Rate Limiting Controls Implemented:

1. **Monthly Limit**: 20,000 requests (API plan limit)
2. **Daily Limit**: 700 requests (conservative daily allocation)
3. **Request Tracking**: Track daily and monthly usage
4. **Automatic Resets**: Daily and monthly counters reset automatically
5. **Usage Monitoring**: `/api/usage/stats` endpoint for monitoring
6. **Cache Extensions**: Much longer cache durations to reduce API calls

## Safety Margin:
- Estimated usage: 15,240 requests/month
- Monthly limit: 20,000 requests/month
- **Buffer**: 4,760 requests (23.8% safety margin)

## Emergency Controls:
- Circuit breaker patterns for failure handling
- Fallback to cached data when limits approached
- Manual override capabilities through usage monitoring endpoint

## Conclusion:
The new configuration should keep us well under the 20,000 monthly limit with a healthy safety margin for manual API calls and unexpected usage spikes.