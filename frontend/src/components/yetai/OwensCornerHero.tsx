'use client';

const HERO_SRC = '/owens-corner/hero.png';

export default function OwensCornerHero() {
  return (
    <header className="owens-corner-hero" aria-labelledby="owens-corner-title">
      <img
        src={HERO_SRC}
        alt="Illustration of Owen and his dog celebrating a winning bet slip with confetti"
        className="owens-corner-hero__img"
        decoding="async"
        fetchPriority="high"
      />
      <div className="owens-corner-hero__overlay">
        <div className="page-eyebrow">Hand-picked picks</div>
        <h1 id="owens-corner-title" className="type-page-title owens-corner-hero__title">
          Owen&apos;s Corner
        </h1>
        <p className="page-sub owens-corner-hero__sub">
          Pending picks and historical results · success rate and units won
        </p>
      </div>
    </header>
  );
}
