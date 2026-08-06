import { ImageResponse } from 'next/og';
import { fetchVaultSnapshot } from '../../../lib/vault';

export const runtime = 'edge';
export const size = { width: 1200, height: 630 };
export const contentType = 'image/png';

type Props = { params: Promise<{ slug: string }> };

export default async function OgImage({ params }: Props) {
  const { slug } = await params;
  let title = 'League Vault';
  let subtitle = 'Fantasy league history';
  let champ = '';
  try {
    const snap = await fetchVaultSnapshot(slug);
    if (snap) {
      title = snap.display_name;
      subtitle = `Est. ${snap.first_season ?? '—'} · ${snap.seasons.length} seasons`;
      if (snap.reigning_champion) {
        champ = `Reigning: ${snap.reigning_champion.display_name} (${snap.reigning_champion.season})`;
      }
    }
  } catch {
    // fall through with defaults
  }

  return new ImageResponse(
    (
      <div
        style={{
          width: '100%',
          height: '100%',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'space-between',
          padding: 64,
          background: 'linear-gradient(145deg, #e8edf2 0%, #d5dde6 55%, #c5d0db 100%)',
          color: '#12161c',
          fontFamily: 'Georgia, serif',
        }}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div
            style={{
              fontSize: 22,
              letterSpacing: 6,
              textTransform: 'uppercase',
              color: '#0f5c4c',
              fontFamily: 'sans-serif',
              fontWeight: 700,
            }}
          >
            League Vault
          </div>
          <div style={{ fontSize: 72, lineHeight: 1.05, fontWeight: 600, maxWidth: 980 }}>
            {title}
          </div>
          <div style={{ fontSize: 28, color: '#5a6573', fontFamily: 'sans-serif' }}>
            {subtitle}
          </div>
        </div>
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'flex-end',
            fontFamily: 'sans-serif',
          }}
        >
          <div style={{ fontSize: 26, color: '#0f5c4c', fontWeight: 600 }}>{champ}</div>
          <div style={{ fontSize: 22, color: '#5a6573' }}>yetai.app</div>
        </div>
      </div>
    ),
    { ...size },
  );
}
