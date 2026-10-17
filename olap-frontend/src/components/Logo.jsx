// Road Runner mark: a geometric running bird with speed lines behind it.
// Same drawing as public/favicon.svg (the browser tab icon).
export default function Logo({ className }) {
  return (
    <svg className={className} viewBox="0 0 32 32" aria-hidden="true">
      <path className="logo-speed" d="M1 20.5h4.5M2 24h3.8" />
      <path className="logo-body" d="M11.5 16.2 1.8 9.6l1.4 3.6 7.4 6.2Z" />
      <path className="logo-body" d="M10 18.6c1.3-4.6 7.7-6.3 11.7-4.3 2.4 1.2 2 4.4-1.3 5.6-3.4 1.3-8.8 1.6-10.4-1.3Z" />
      <path className="logo-body" d="m18.7 15.6 3.5-6.4 3.6 1.4-3.9 6.4Z" />
      <circle className="logo-body" cx="24.2" cy="9.6" r="2.9" />
      <path className="logo-body" d="M25 7c-1.9-2.4-4.4-3.5-6.8-3.3 1.8 1.1 3 2.7 3.8 4.5Z" />
      <path className="logo-beak" d="m26.8 8.9 4.7 1.2-4.6 1.3Z" />
      <circle className="logo-eye" cx="24.9" cy="9.2" r="0.75" />
      <path className="logo-legs" d="m16.2 20.2 2.6 3.7-.4 4.1M14.4 20.4l-2.3 3.3-3.4 1.4M18.4 28h2.2M8.7 25.1l-1.3 1.7" />
    </svg>
  )
}
