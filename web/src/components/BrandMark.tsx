// The mark, in a ring one point of light keeps travelling around. Three places show the
// brand -- the sidebar, the login card, the account pages -- and they should all catch the
// same light, so the halo lives with the mark rather than at each call site.
export function BrandMark() {
  return (
    <span className="brand-mark-wrap">
      <img className="brand-mark" src="/logo.png" alt="" width={34} height={34} />
    </span>
  );
}
