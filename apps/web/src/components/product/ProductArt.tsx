// A product's picture, drawn from its category: the catalogue has no photos,
// so each category gets an illustration on its own colour, with the brand.
import React from "react";

type Art = { from: string; to: string; icon: React.ReactNode };

const stroke = { fill: "none", stroke: "currentColor", strokeWidth: 3, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };

const ARTS: Record<string, Art> = {
  "gia-dung/may-loc-khong-khi": {
    from: "#e6f2ec",
    to: "#c9e3d5",
    icon: (
      <g {...stroke}>
        <rect x="34" y="18" width="52" height="84" rx="12" />
        <path d="M46 34h28M46 44h28M46 54h28M46 64h28" />
        <circle cx="60" cy="86" r="6" />
        <path d="M96 40c8 4 8 14 0 18M102 34c13 7 13 23 0 30" opacity=".6" />
      </g>
    ),
  },
  "gia-dung/may-loc-nuoc": {
    from: "#e5f0f8",
    to: "#c7dcee",
    icon: (
      <g {...stroke}>
        <rect x="36" y="22" width="48" height="80" rx="8" />
        <path d="M60 40c-8 10-12 16-12 22a12 12 0 0 0 24 0c0-6-4-12-12-22z" />
        <path d="M44 92h32" />
      </g>
    ),
  },
  "gia-dung/quat": {
    from: "#eef3e6",
    to: "#d8e6c4",
    icon: (
      <g {...stroke}>
        <circle cx="60" cy="48" r="28" />
        <path d="M60 48c0-14 10-20 14-14s-8 14-14 14zm0 0c12 7 12 19 5 20s-9-13-5-20zm0 0c-12 7-23 1-20-5s16-3 20 5z" />
        <path d="M60 76v22M44 102h32" />
      </g>
    ),
  },
  "gia-dung/noi-chien": {
    from: "#f8eee4",
    to: "#efd8c2",
    icon: (
      <g {...stroke}>
        <path d="M30 44h60l-6 52H36z" />
        <rect x="38" y="24" width="44" height="20" rx="8" />
        <circle cx="60" cy="68" r="10" />
        <path d="M90 60h12" />
      </g>
    ),
  },
  "gia-dung/phu-kien": {
    from: "#eef0f2",
    to: "#d6dbe0",
    icon: (
      <g {...stroke}>
        <rect x="32" y="30" width="56" height="60" rx="10" />
        <path d="M42 30v60M52 30v60M62 30v60M72 30v60M82 30v60" opacity=".55" />
      </g>
    ),
  },
  "gia-dung/combo": {
    from: "#f4efe0",
    to: "#e7dbb5",
    icon: (
      <g {...stroke}>
        <rect x="26" y="46" width="68" height="50" rx="6" />
        <path d="M26 60h68M60 46v50" />
        <path d="M60 46c-6-14-22-14-20-4 2 8 20 4 20 4zm0 0c6-14 22-14 20-4-2 8-20 4-20 4z" />
      </g>
    ),
  },
  "thoi-trang/giay": {
    from: "#f3e9ee",
    to: "#e6cfdb",
    icon: (
      <g {...stroke}>
        <path d="M22 78c0-10 4-24 8-30 6 6 16 8 24 4 10 12 24 16 40 18 6 1 10 6 10 12v4H22z" />
        <path d="M22 86h82M46 58l6 6M54 54l6 6" />
      </g>
    ),
  },
  "thoi-trang/ao-khoac": {
    from: "#ece9f5",
    to: "#d5cfea",
    icon: (
      <g {...stroke}>
        <path d="M44 24l16 10 16-10 20 14-8 18-8-4v48H40V52l-8 4-8-18z" />
        <path d="M60 34v68M54 50h-6M54 64h-6" />
      </g>
    ),
  },
  "thoi-trang/phu-kien": {
    from: "#f2ece4",
    to: "#e2d5c4",
    icon: (
      <g {...stroke}>
        <path d="M30 60h60v34a8 8 0 0 1-8 8H38a8 8 0 0 1-8-8z" />
        <path d="M44 60V48a16 16 0 0 1 32 0v12" />
      </g>
    ),
  },
  "me-be": {
    from: "#fbeef0",
    to: "#f3d3da",
    icon: (
      <g {...stroke}>
        <circle cx="60" cy="54" r="24" />
        <path d="M51 50h.01M69 50h.01M52 62c5 5 11 5 16 0" />
        <path d="M60 30c-2-8 6-10 8-6" />
        <path d="M44 86l-6 14M76 86l6 14" />
      </g>
    ),
  },
};

function artFor(category: string): Art {
  return ARTS[category] || ARTS[category.split("/")[0]] || ARTS["gia-dung/phu-kien"];
}

export default function ProductArt({
  category,
  brand,
  size = "card",
}: {
  category: string;
  brand?: string;
  size?: "card" | "hero" | "thumb";
}) {
  const art = artFor(category);
  return (
    <div
      className={`s-art s-art-${size}`}
      style={{ background: `linear-gradient(145deg, ${art.from}, ${art.to})` }}
      aria-hidden="true"
    >
      <svg viewBox="0 0 120 120" className="s-art-icon">
        {art.icon}
      </svg>
      {brand && size !== "thumb" && <span className="s-art-brand">{brand}</span>}
    </div>
  );
}
