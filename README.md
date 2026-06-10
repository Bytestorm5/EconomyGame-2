# Village Economy

A deliberately-scoped MVP: a medieval village economic simulation with a
playable city-builder-lite on top. You are **one business among many** — every
NPC in the village runs their own little tycoon operation, and the player
simply joins the same economy.

## Run it

```bash
pip install -r requirements.txt
python run_game.py            # the game
python run_headless.py 30 42  # 30 sim-days, seed 42, economy stats only
python -m pytest tests/      # test suite
```

## How the simulation works

- **People & needs.** Hunger rises every tick. Hungry people eat from their
  inventory, or buy food — comparing price per point of food value, so cheap
  bran competes with bread.
- **Knowledge graph.** Worldgen wires each person to their nearest plot
  neighbours plus a couple of random others. A buyer only sees prices from
  people they *know*, and buys from the cheapest. If nobody they know sells
  the product, they ask a random acquaintance to look; the search recurses
  outward with decaying probability (`REFERRAL_CONTINUE_PROB ** depth`). A
  successful referral forms a permanent new knowledge edge. Press **K**
  in-game to watch the web grow.
- **Production.** Every product is made by one machine type with the same
  tycoon shape: inputs → cycle → outputs. Level `L` runs `2^(L-1)` batches per
  cycle; upgrade costs grow exponentially. Machines sit in slots on pre-set
  plots and run automatically whenever their owner has the inputs. Owners
  (player included) restock inputs daily through the knowledge graph.
- **Prices.** NPCs nudge prices up when they sell out and down when stock
  piles up, with a cost-aware floor so nobody sells below input cost. The
  player sets their own prices in the building panel.
- **The tithe.** A small daily % of everyone's coin is pooled and shared back
  equally. This is the MVP stand-in for wages — without some recirculation,
  money drains one-way up the production chain and consumers go broke. Total
  money in the world is exactly conserved.

### Product chain

```
Wheat Farm ──> grain ──> Mill ──> flour ──> Bakery ──> bread (food)
                          └────> bran (by-product, cheap food)
Woodcutter ──> wood ───────────────────────────┘ (bakery fuel)
```

## Playing

Click any plot to inspect it (NPC businesses are view-only). On **your plot**
(gold border) you can build machines in empty slots, upgrade them, demolish
them, and set sale prices with the +/- buttons. NPCs will find you through
the knowledge graph and buy what you sell. `Space` pauses, `1/2/3` sets speed,
`K` toggles the knowledge-web overlay, `Esc` closes menus.

## Code layout

| Path | What |
|---|---|
| `village/registry.py` | Content registry — all content is data registered by id |
| `village/content/` | Product and machine (recipe) definitions |
| `village/sim/` | The simulation: people, trade/referrals, machines, plots, world tick |
| `village/ui/` | pygame UI: map view, building panel, HUD |
| `run_headless.py` | Run the economy with no UI and print health stats |

The sim has **no dependency on pygame** — `village/sim/` and
`village/content/` run headless, which is how the balance numbers in
`village/sim/config.py` were tuned.

> **Note:** `village/registry.py` is a fresh implementation — the original
> project's registry file wasn't available when this was built. It keeps the
> same role (typed categories, id-keyed defs, duplicate protection); swap in
> the original by matching the small API in that file.

## Art

All visuals are currently solid-color placeholder blocks. Real art can be
dropped into `assets/` file-by-file with no code changes — see
[ASSETS.md](ASSETS.md) for the full wishlist and file names.
