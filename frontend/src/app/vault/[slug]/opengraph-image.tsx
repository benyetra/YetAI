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
          position: 'relative',
          overflow: 'hidden',
          background:
            'radial-gradient(circle at 84% 18%, rgba(198, 160, 53, 0.24) 0, transparent 30%), radial-gradient(circle at 16% 80%, rgba(20, 122, 95, 0.4) 0, transparent 34%), linear-gradient(145deg, #07100d 0%, #0f3d2e 54%, #081612 100%)',
          color: '#eef3ef',
          fontFamily: 'Georgia, serif',
        }}
      >
        <div
          style={{
            position: 'absolute',
            right: -42,
            bottom: -18,
            width: 510,
            height: 210,
            borderTop: '2px solid rgba(238, 243, 239, 0.12)',
            display: 'flex',
            gap: 58,
            transform: 'skewX(-12deg)',
          }}
        >
          {Array.from({ length: 8 }).map((_, index) => (
            <div
              key={index}
              style={{
                width: 2,
                height: 210,
                background: 'rgba(238, 243, 239, 0.12)',
              }}
            />
          ))}
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 48 }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16, maxWidth: 860 }}>
            <div
              style={{
                fontSize: 24,
                letterSpacing: 7,
                textTransform: 'uppercase',
                color: '#c6a035',
                fontFamily: 'sans-serif',
                fontWeight: 800,
              }}
            >
              League Vault
            </div>
            <div style={{ fontSize: 88, lineHeight: 0.94, fontWeight: 700 }}>
              {title}
            </div>
            <div style={{ fontSize: 30, color: 'rgba(238, 243, 239, 0.72)', fontFamily: 'sans-serif' }}>
              {subtitle}
            </div>
          </div>
          <div
            style={{
              position: 'relative',
              width: 190,
              height: 180,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              marginTop: 16,
            }}
          >
            <div
              style={{
                position: 'absolute',
                left: 6,
                top: 50,
                width: 48,
                height: 58,
                border: '10px solid #c6a035',
                borderRight: 0,
                borderRadius: '30px 0 0 30px',
              }}
            />
            <div
              style={{
                position: 'absolute',
                right: 6,
                top: 50,
                width: 48,
                height: 58,
                border: '10px solid #c6a035',
                borderLeft: 0,
                borderRadius: '0 30px 30px 0',
              }}
            />
            <div
              style={{
                position: 'absolute',
                top: 34,
                width: 104,
                height: 88,
                background: 'linear-gradient(135deg, #f0d77a 0%, #c6a035 58%, #8b6b16 100%)',
                border: '4px solid #f4df93',
                borderRadius: '10px 10px 34px 34px',
              }}
            />
            <div
              style={{
                position: 'absolute',
                top: 120,
                width: 30,
                height: 28,
                background: '#c6a035',
                borderLeft: '4px solid #f4df93',
                borderRight: '4px solid #8b6b16',
              }}
            />
            <div
              style={{
                position: 'absolute',
                top: 148,
                width: 96,
                height: 20,
                background: '#c6a035',
                border: '4px solid #f4df93',
                borderRadius: 4,
              }}
            />
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
          <div style={{ fontSize: 28, color: '#d6bf67', fontWeight: 700 }}>{champ}</div>
          <div style={{ fontSize: 22, color: 'rgba(238, 243, 239, 0.62)' }}>yetai.app</div>
        </div>
      </div>
    ),
    { ...size },
  );
}
