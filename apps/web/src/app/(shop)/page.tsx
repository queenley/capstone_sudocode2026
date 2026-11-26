import { AssistantSection, FamilySection, HomeHero, RangeSection, TermsSection } from "@/features/home/sections";

/*
  type: product (a shop selling physical goods online; site-kind other)
  deal: hero product (a stand-in photograph), nav nav-split, close close-type, footer footer-columns,
        rhythm brand-band, buttons pill, mark: Quivo's own logo; type Work Sans (sets Vietnamese)
  screens: hero 1 · #hang 1 · #tro-ly 1 · #me-be 1 · #mua-hang 1 (2 on a tablet and a phone) · footer
  The page stays five screens: the range tiles already show each appliance, so no section repeats them.
  Every photograph on this page is a licensed stand-in (public/assets/img/credits.json, /products: the shop's
  catalogue photos from data/seed/catalog), listed on /anh and in the footer's credits line.
*/
export default function HomePage() {
  return (
    <>
      <HomeHero />
      <RangeSection />
      <AssistantSection />
      <FamilySection />
      <TermsSection />
    </>
  );
}
