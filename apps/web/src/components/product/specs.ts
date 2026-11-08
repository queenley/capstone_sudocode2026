// The specs a shopper chooses by, read from the product description the
// catalogue already sends. scripts/seed/btc_catalog.py writes the organisers'
// attributes there as "Label: value" lines (its LABELS); this file only reads
// them back for display and filtering, so a product without them shows nothing.

/** The seed's label for each attribute this file uses. */
const LABELS = {
  room: "Diện tích phòng phù hợp (m²)",
  stages: "Số cấp lọc",
  volume: "Dung tích (ml)",
  weight: "Tải trọng tối đa (kg)",
  lock: "Khóa an toàn trẻ em",
  material: "Chất liệu",
  warranty: "Bảo hành (tháng)",
  returns: "Đổi trả trong (ngày)",
} as const;

function lines(description: string | null | undefined): Map<string, string> {
  const out = new Map<string, string>();
  for (const line of (description || "").split("\n")) {
    const at = line.indexOf(": ");
    if (at > 0) out.set(line.slice(0, at).trim(), line.slice(at + 2).trim());
  }
  return out;
}

function positive(value: string | undefined): number | null {
  const n = Number(value);
  return Number.isFinite(n) && n > 0 ? n : null;
}

/** The room size a product suits, in m², or null when the catalogue does not say. */
export function roomArea(description: string | null | undefined): number | null {
  return positive(lines(description).get(LABELS.room));
}

/** Up to *limit* short spec labels, the one a shopper decides by first. */
export function keySpecs(description: string | null | undefined, limit = 2): string[] {
  const d = lines(description);
  const n = (label: string) => positive(d.get(label));
  const out: string[] = [];
  const room = n(LABELS.room);
  if (room) out.push(`Phòng đến ${room} m²`);
  const stages = n(LABELS.stages);
  if (stages) out.push(`${stages} cấp lọc`);
  const volume = n(LABELS.volume);
  if (volume) out.push(`${volume} ml`);
  const weight = n(LABELS.weight);
  if (weight) out.push(`Tải trọng ${weight} kg`);
  if (d.get(LABELS.lock) === "Có") out.push("Khóa an toàn trẻ em");
  const material = d.get(LABELS.material);
  if (material) out.push(material);
  const warranty = n(LABELS.warranty);
  if (warranty) out.push(`Bảo hành ${warranty} tháng`);
  const returns = n(LABELS.returns);
  if (returns) out.push(`Đổi trả ${returns} ngày`);
  return out.slice(0, limit);
}
