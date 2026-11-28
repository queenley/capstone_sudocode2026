import { HomeStore } from "@/features/home/sections";

/*
  The store front: a hero whose window turns through four featured products (one from each department), the
  departments as a row of pictures, the next featured products moving four at a time, one row of four per
  department with "Xem thêm", and the shop's terms. Photographs are licensed stand-ins
  (public/assets/img/credits.json) or the catalogue's own (/products), listed on /anh.
*/
export default function HomePage() {
  return <HomeStore />;
}
