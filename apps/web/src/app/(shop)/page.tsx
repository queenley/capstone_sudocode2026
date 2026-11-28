import { CategoryStrip, HomeBanner, ProductSections, TermsStrip } from "@/features/home/sections";

/*
  The store front: a one-line banner, the departments as a row of pictures, the featured products moving four at a
  time, one row of four per department with "Xem thêm", and the shop's terms. Photographs are licensed stand-ins
  (public/assets/img/credits.json) or the catalogue's own (/products), listed on /anh.
*/
export default function HomePage() {
  return (
    <>
      <HomeBanner />
      <CategoryStrip />
      <ProductSections />
      <TermsStrip />
    </>
  );
}
