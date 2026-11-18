import { createElement, type ReactNode } from 'react';

/** Shown wherever a pick would render for a market the backend record gate withholds. */
export const PICK_WITHHELD_NOTE =
  'No pick: this market has not proved itself against the line yet';

/** The backend sets `pick_withheld` (a reason string) on rows from a withheld market. */
export function isPickWithheld(row: Record<string, unknown> | null | undefined): boolean {
  const v = row?.pick_withheld;
  return v !== null && v !== undefined && v !== '' && v !== false;
}

/** A real side from the backend; NO_PLAY / PASS / empty are "no pick". */
export function isRealPickSide(value: unknown): boolean {
  const s = String(value ?? '').trim().toUpperCase();
  return s !== '' && s !== 'NO_PLAY' && s !== 'PASS' && s !== 'NONE' && s !== 'NULL';
}

/** Neutral muted note for a table cell (text is in the DOM, full sentence in the tooltip too). */
export function pickWithheldNote(): ReactNode {
  return createElement(
    'span',
    { className: 'dim', title: PICK_WITHHELD_NOTE, style: { fontSize: 11, whiteSpace: 'normal' } },
    PICK_WITHHELD_NOTE,
  );
}

/** Pick-cell content: the note for a withheld row, else the stored pick (or "—"). */
export function pickCell(row: Record<string, unknown>, ...stored: unknown[]): ReactNode {
  if (isPickWithheld(row)) return pickWithheldNote();
  const v = stored.find((s) => s !== null && s !== undefined && s !== '');
  return v === undefined ? '—' : String(v);
}
