You prepare the ASR ground truth of a Vietnamese phone call to an electronics shop.
A text-to-speech voice will read each line aloud: the customer's lines, and in a whole dialogue the shop agent's lines too. A speech recogniser will then be scored against that same text.
Rewrite each line exactly as its speaker says it out loud, in the style of BTC's `asr/ground_truth.json`.

Rules for `spoken_text`:
1. Change only what is not plain spoken words: numbers, money, dates, units, percentages, phone numbers, order codes, product codes, brand or model names, abbreviations and symbols. Keep every other word, in the same order. Do not add, drop, fix or reword anything else. Typos, slang and filler words stay as they are.
2. Write everything in lowercase. Keep commas, question marks and full stops.
3. No digits may remain.
   - Money is said the way people say it: "5.200.000đ" -> "năm triệu hai trăm nghìn", "4tr8" -> "bốn triệu tám", "500k" -> "năm trăm nghìn".
   - Areas and sizes: "25m2" -> "hai mươi lăm mét vuông", "size 41" -> "size bốn mươi mốt".
   - Dates: "22/10" -> "hai mươi hai tháng mười".
   - Phone and ID numbers are read digit by digit: "0912..." -> "không chín một hai ...".
   - Order codes are read letter by letter, then the digits as a number: "OD312456" -> "ô đê ba trăm mười hai nghìn bốn trăm năm mươi sáu".
4. Brand and model names are written the way a Vietnamese speaker pronounces them: "AirPure X" -> "e pia x", "RO9" -> "rô chín", "BTC" -> "bê tê xê", "COD" -> "cê ô đê". A product code such as "SKU-AP-X" is never read aloud; say the product's name from `products` instead.
5. If a line has nothing to change, copy it unchanged, only in lowercase.

Rules for `entities`. These are the values a line states, under BTC's keys:
- Only fill a value the line actually says. Leave everything else null. Never take a value from another line or from `products` unless the line names that product.
- Money, areas and day counts are numbers: "năm triệu bảy" -> 5700000, "hai mươi lăm mét vuông" -> 25, "giao trong hai ngày" -> 2.
- Dates are `YYYY-MM-DD`; the year is the call's year.
- `sku` must be one of the keys of `products`, and only when the line names that product or its model.
- `payment` is "COD" for cash on delivery (thu hộ, nhận hàng trả tiền) and "bank" for transfer (chuyển khoản).
- Customer lines carry what the customer tells: room area, children at home, budget, a competitor's price, payment, the reason not to buy yet, sizes, colour, their phone.
- Agent lines carry what the shop tells: the price, the promotion's last day, delivery days, warranty months, return days, the free-shipping minimum, fees, a refund, whether it is in stock, the restock date.
- `blocker` is the reason the customer is not buying yet. Fill it only when the line says that reason, and use the label that matches it exactly:
  - "can hoi chong" / "can hoi vo": must ask the husband / wife;
  - "can hoi nguoi nha": must talk with the family;
  - "so sanh gia": comparing prices;
  - "vuot ngan sach": over budget;
  - "cho luong": waiting for payday;
  - "can suy nghi them": wants to think it over.

  "I'll call back later" with no reason given leaves it null.

Return one item per line, with the same `idx`, in order.
