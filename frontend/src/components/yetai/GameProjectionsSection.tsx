'use client';

import { useMemo } from 'react';
import GameProjectionsGrid, {
  type GameProjectionSlipPick,
  type GameProjectionsVariant,
} from '@/components/yetai/MlbGameProjectionsGrid';
import { gameProjectionRows } from '@/lib/gameProjectionsFromApi';

export default function GameProjectionsSection({
  variant,
  data,
  loading,
  isPastDate,
  onAddToSlip,
}: {
  variant: GameProjectionsVariant;
  data: Record<string, Array<Record<string, unknown>>> | null;
  loading: boolean;
  isPastDate: boolean;
  onAddToSlip?: (pick: GameProjectionSlipPick) => void;
}) {
  const rows = useMemo(() => gameProjectionRows(variant, data), [variant, data]);

  return (
    <section style={{ marginBottom: 24 }}>
      <div style={{ marginBottom: 12 }}>
        <h2 className="type-section-title" style={{ margin: 0 }}>
          Game projections
        </h2>
        <p className="dim" style={{ fontSize: 12, margin: '4px 0 0' }}>
          Win-probability and projected score by ML model
        </p>
      </div>
      <GameProjectionsGrid
        rows={rows}
        loading={loading}
        isPastDate={isPastDate}
        variant={variant}
        onAddToSlip={onAddToSlip}
      />
    </section>
  );
}
