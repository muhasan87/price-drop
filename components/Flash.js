export default function Flash({ flash }) {
  if (!flash) return null;
  return <div className={`flash ${flash.type}`}>{flash.message}</div>;
}
