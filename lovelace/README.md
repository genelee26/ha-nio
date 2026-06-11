# Plain-YAML fallback card

You do **not** need this if you use the bundled **NIO Car Card** (the visual
editor card the integration registers automatically — see the main README).

This is for people who would rather not use a custom card at all. It is a stock
`picture-glance` card pointing at the bundled vehicle render, with no extra
frontend dependencies.

## Use

1. Open `nio_card_plain.yaml`.
2. Replace the two placeholders:
   - `__PREFIX__` → your entity prefix, i.e. the device name lowercased with
     `_` (e.g. `nio_ec6`). Check under *Settings → Devices → your NIO* if unsure.
   - `__CAR_IMAGE__` → a bundled render path, `/nio_static/cars/<model>_<color>.webp`
     (e.g. `/nio_static/cars/ec6_star_gray.webp`). The colour slugs per model
     are listed in `/nio_static/cars/cars_manifest.json`.
3. Paste the result into a Manual card (or your dashboard YAML).

The bundled custom card does all of this — image selection, the status popup,
the studio backdrop — from a visual editor instead, and resolves entities from
the device so it survives entity-id renames. Prefer it unless you specifically
want raw YAML.
