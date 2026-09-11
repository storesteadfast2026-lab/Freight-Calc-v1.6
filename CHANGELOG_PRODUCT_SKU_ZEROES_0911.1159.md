# Product SKU leading zeroes — 0911.1159

## Scope

- Preserve meaningful leading zeroes when validating `products.csv`.
- Treat codes such as `0034` and `34` as distinct Product SKUs.
- Continue trimming surrounding spaces and comparing letters without case sensitivity.
- Keep exact duplicate Product codes isolated for review.

## Safety

- Product source rows remain reference-only staging data.
- No operational `Product`, freight rate, zone, carrier, fuel or calculator data is modified.
- No database migration is required.

## Expected revalidation result

For the source previously reported as 38,684 rows:

- valid rows should increase from 38,649 to 38,663;
- rejected rows should decrease from 35 to 21;
- duplicate Product SKUs should decrease from 7 to 0, provided no other exact duplicates exist in that same source snapshot.

The 21 malformed CSV rows remain isolated for review.
