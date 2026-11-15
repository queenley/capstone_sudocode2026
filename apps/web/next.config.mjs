// The staff workspaces have one route per section (/ban-hang/don-hang, /admin/skills): the old ?tab= links, and the
// workspace's bare address, go to the section, before any page renders. The slugs are the ones in
// src/features/sales/nav.tsx and src/features/admin/nav.tsx.
const SALES = { overview: "tong-quan", conversations: "hoi-thoai", orders: "don-hang", callbacks: "hen-goi-lai" };
const ADMIN = {
  knowledge: "kien-thuc",
  policies: "chinh-sach",
  skills: "skills",
  improvement: "cai-tien",
  evaluation: "danh-gia",
  proposals: "de-xuat",
  catalog: "san-pham",
  staff: "nhan-su",
};

function workspace(base, tabs, home) {
  return [
    ...Object.entries(tabs).map(([tab, slug]) => ({
      source: base,
      has: [{ type: "query", key: "tab", value: tab }],
      destination: `${base}/${slug}`,
      permanent: false,
    })),
    { source: base, destination: `${base}/${tabs[home]}`, permanent: false },
  ];
}

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: 'standalone',
  async redirects() {
    return [...workspace("/ban-hang", SALES, "overview"), ...workspace("/admin", ADMIN, "knowledge")];
  },
};

export default nextConfig;
