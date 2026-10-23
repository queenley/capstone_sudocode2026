// How customers reach the shop besides the website chat. Set at build time:
//   NEXT_PUBLIC_HOTLINE       the number shown and dialled (tel:), e.g. "1900 6868"
//   NEXT_PUBLIC_ZALO_OA_ID    the Zalo Official Account id; empty hides the Zalo links
export const HOTLINE = process.env.NEXT_PUBLIC_HOTLINE || "1900 6868";
const ZALO_OA_ID = process.env.NEXT_PUBLIC_ZALO_OA_ID || "";
export const ZALO_URL = ZALO_OA_ID ? `https://zalo.me/${ZALO_OA_ID}` : "";
