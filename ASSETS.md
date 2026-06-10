# Asset wishlist

Every sprite is requested through `village/ui/assets.py:get_tile(name, ...)`.
Drop a PNG named `<name>.png` into `assets/` and it is picked up automatically
(scaled to fit); anything missing falls back to a solid color block, which is
what ships today.

## Requested files

| File | Used where | Current placeholder |
|---|---|---|
| `assets/terrain_grass.png` | Map background (tileable, drawn stretched for now) | flat green |
| `assets/terrain_road.png` | Road grid strips between blocks | flat grey-brown |
| `assets/plot_ground.png` | Owned parcel interior ground | flat tan |
| `assets/plot_ground_unowned.png` | Unowned (overgrown) parcel ground | flat grey-green |
| `assets/machine_wheat_farm.png` | Machine block on map (~56×52 px) | green block |
| `assets/machine_woodcutter.png` | Machine block on map | dark brown block |
| `assets/machine_mill.png` | Machine block on map | grey block |
| `assets/machine_bakery.png` | Machine block on map | orange block |

Machine fallback colors come from each `MachineDef.color` in
`village/content/machines.py`, so new machine content automatically gets a
placeholder and an asset slot (`machine_<id>.png`).

## Not yet wired up (future)

- Product icons (`ProductDef.color` already reserves a swatch per product) —
  would go in the sidebar inventory/sale lists.
- People sprites — people are currently abstract (a name label per plot).
- UI chrome (panel background, buttons) — plain rects for now.
