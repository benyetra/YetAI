export type OddsFormat = 'american' | 'decimal' | 'fractional';

export type SingleBetResult = {
  potentialPayout: number;
  impliedProbability: number;
};

export type ParlayLeg = { odds: string };

export type ParlayResult = {
  combinedDecimal: number;
  combinedAmerican: string;
  impliedProbability: number;
  potentialPayout: number;
  profit: number;
};

export function oddsToDecimal(oddsStr: string, format: OddsFormat): number | null {
  const s = oddsStr.trim();
  if (!s) return null;

  switch (format) {
    case 'american': {
      const a = parseInt(s, 10);
      if (Number.isNaN(a) || a === 0) return null;
      return a > 0 ? a / 100 + 1 : 100 / Math.abs(a) + 1;
    }
    case 'decimal': {
      const d = parseFloat(s);
      if (Number.isNaN(d) || d <= 1) return null;
      return d;
    }
    case 'fractional': {
      const parts = s.split('/').map(Number);
      if (parts.length !== 2 || parts.some(Number.isNaN) || parts[1] === 0) return null;
      return parts[0] / parts[1] + 1;
    }
    default:
      return null;
  }
}

export function calculateSingleBet(
  betAmount: number,
  odds: string,
  format: OddsFormat,
): SingleBetResult | null {
  if (!Number.isFinite(betAmount) || betAmount <= 0) return null;

  const decimal = oddsToDecimal(odds, format);
  if (decimal === null) return null;

  let potentialPayout: number;
  let impliedProbability: number;

  if (format === 'american') {
    const american = parseInt(odds.trim(), 10);
    if (Number.isNaN(american)) return null;
    if (american > 0) {
      potentialPayout = betAmount + betAmount * (american / 100);
      impliedProbability = 100 / (american + 100);
    } else {
      potentialPayout = betAmount + betAmount / (Math.abs(american) / 100);
      impliedProbability = Math.abs(american) / (Math.abs(american) + 100);
    }
  } else {
    potentialPayout = betAmount * decimal;
    impliedProbability = 1 / decimal;
  }

  return { potentialPayout, impliedProbability };
}

function decimalToAmerican(decimal: number): string {
  if (!Number.isFinite(decimal) || decimal <= 1) return '';
  if (decimal >= 2) {
    return `+${Math.round((decimal - 1) * 100)}`;
  }
  return String(Math.round(-100 / (decimal - 1)));
}

export function calculateParlay(
  betAmount: number,
  legs: ParlayLeg[],
  format: OddsFormat,
): ParlayResult | null {
  if (!Number.isFinite(betAmount) || betAmount <= 0 || legs.length < 2) return null;

  let combined = 1;
  for (const leg of legs) {
    const d = oddsToDecimal(leg.odds, format);
    if (d === null) return null;
    combined *= d;
  }

  const potentialPayout = betAmount * combined;
  return {
    combinedDecimal: combined,
    combinedAmerican: decimalToAmerican(combined),
    impliedProbability: 1 / combined,
    potentialPayout,
    profit: potentialPayout - betAmount,
  };
}
