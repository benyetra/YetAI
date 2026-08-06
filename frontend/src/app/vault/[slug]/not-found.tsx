export default function VaultNotFound() {
  return (
    <div className="vault-root" style={{ padding: '3rem 1rem' }}>
      <h1 className="vault-display" style={{ fontSize: '2rem' }}>
        League not found
      </h1>
      <p className="vault-muted">This vault slug does not exist or is not public.</p>
    </div>
  );
}
