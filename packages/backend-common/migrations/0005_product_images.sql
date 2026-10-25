-- A product's photo (a file the storefront serves) and its credit: openly licensed
-- pictures need their title, author, licence and source shown with them.
ALTER TABLE commerce.products ADD COLUMN IF NOT EXISTS image_url text;
ALTER TABLE commerce.products ADD COLUMN IF NOT EXISTS image_credit jsonb;
