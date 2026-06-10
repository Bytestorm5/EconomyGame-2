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
- **Prices.** NPC sellers do supply-demand price discovery from what they
  personally observe each day: sold out → raise; nothing sold (with stock on
  hand) → lower; selling steadily with stock left → hold. A cost-aware floor
  keeps nobody selling below input cost. The player sets their own prices in
  the building panel.
- **NPC investment.** Every 7 days (staggered per person) an NPC may make one
  move: *upgrade* a machine that actually runs (uptime ≥ 60%) and whose
  output kept selling out that week, or *build* the best-margin machine —
  but only if its primary output has no in-stock seller anywhere in their
  knowledge circle (a visible supply gap). Their market view is limited to
  who they know; build/upgrade coin goes to the village treasury and comes
  back out through the tithe.
- **Make-to-stock.** NPC machines pause when every output already has ~5
  days of observed sales in stock (or any output is grossly overstocked), so
  by-product demand can't pile mountains of the main product. Player
  machines never auto-pause.
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

**Your unfair advantage:** your auto-buy (machine inputs and food) sees every
seller in the village, while NPCs only see the people they know.

**Metrics:** every machine row shows its 7-day uptime; hover it (in the panel
or on the map) for yesterday's resource consumption/production. Hover a good
in *Goods for Sale* for yesterday's profit, units produced, units consumed by
the owner's own machines, and sales count.

## Code layout

| Path | What |
|---|---|
| `village/register.py` | Content registry (ported from the original project): scans content folders, validates JSON against Pydantic models |
| `village/objects.py` | Pydantic models for content (`ProductDef`, `MachineDef`) |
| `content/<ModelName>/*.json` | The actual game content, one JSON file per definition |
| `content_custom/<mod>/` | Mod folders, loaded after `content/` so same-id definitions override |
| `village/content/` | Typed views (`PRODUCTS`, `MACHINES`) the game code reads |
| `village/sim/` | The simulation: people, trade/referrals, machines, plots, world tick |
| `village/ui/` | pygame UI: map view, building panel, HUD, tooltips |
| `run_headless.py` | Run the economy with no UI and print health stats |

The sim has **no dependency on pygame** — `village/sim/` and
`village/content/` run headless, which is how the balance numbers in
`village/sim/config.py` were tuned.

Adding content is data-only: drop a JSON file into `content/ProductDef/` or
`content/MachineDef/` (folder name = Pydantic model class in
`village/objects.py`). Mods in `content_custom/` override by id.

## Art

All visuals are currently solid-color placeholder blocks. Real art can be
dropped into `assets/` file-by-file with no code changes — see
[ASSETS.md](ASSETS.md) for the full wishlist and file names.
