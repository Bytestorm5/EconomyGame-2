# Village Economy

A deliberately-scoped MVP: a medieval village economic simulation with a
playable city-builder-lite on top. You are **one business among many** — every
NPC in the village runs their own little tycoon operation, and the player
simply joins the same economy.

## Run it

```bash
pip install -r requirements.txt
python run_game.py                                # the game
python run_game.py --blocks 4x3 --npcs 30 --seed 7   # a bigger village
python run_headless.py --days 30 --seed 42        # economy stats, no UI
python run_headless.py --days 90 --csv econ.csv   # per-day balance time series
python -m pytest tests/                          # test suite
```

`--blocks WxH` sets the village size as a road grid of blocks (4 parcels per
block); `--npcs` sets the population. Leftover parcels start unowned.

## How the simulation works

- **People & demands.** Consumer needs are data, not code: each
  `content/DemandDef/*.json` defines what products fulfill a demand (and how
  well), what makes it grow (per tick / per day), and two *urgency*
  thresholds that cascade: at **want**, a person fulfills it from home
  reserves or orders at a reasonable delivered price (skipping it if too
  expensive); at **need**, they pay whatever they can afford and ask around
  (referrals) if nobody they know sells. Purchases are vehicle trips that
  take time: people order a couple of days' worth at once (amortizing the
  trip's base cost) and wait for the cart rather than double-ordering. *Loyalty* makes consumers sticky —
  per fulfillment there's a chance they return straight to their last seller
  (even for a different product) or re-buy their last product (even from a
  different seller), zooming back out to comparison shopping whenever the
  remembered option is out of stock or too expensive. Hunger is just the
  first demand definition.
- **Knowledge graph.** Worldgen wires each person to their nearest
  neighbours plus a couple of random others. A buyer only sees offers from
  people they *know*. If nobody known sells a product, they ask a random
  acquaintance to look; the search recurses outward with decaying probability
  (`REFERRAL_CONTINUE_PROB ** depth`), and a successful referral forms a new
  knowledge edge. The graph is alive in both directions: every hour each
  edge to a *seller* has a 0.2% chance of being forgotten unless the person
  bought from them that very tick (purely social edges never fade, and
  nobody forgets below a small floor). Press **K** to watch the web churn.
- **Advertising.** Sellers buy edges: each `content/AdvertisingDef/*.json`
  campaign reaches N random people — village-wide (Town Crier, Festival) or
  distance-weighted hyper-local (Handbills, P ∝ exp(-dist/falloff)) from a
  chosen parcel. Attention pushes back: every impression adds ad fatigue,
  and anyone who hears of you more than 3 times *intentionally forgets* you
  and stays deaf to your ads until the fatigue decays through the normal
  forget flow. NPCs advertise when sellable stock sits unsold, but track
  whether the campaign moved product and give up for two weeks when it
  doesn't. The player runs campaigns from any owned parcel's panel.
- **Personal stockpiles.** A person will not let themselves starve if they
  can help it: every day they top their home pantry back up to ~2 days of
  every demand before hunger bites — at reasonable prices normally, at any
  affordable price once the pantry is empty. (Businesses may misjudge their
  stockpiles; people don't.)
- **Parcels, vehicles & shipping.** Land is divided into pre-set parcels on
  a road grid, each with its own separate, capacity-limited inventory (a
  bare parcel holds a little; stores and warehouses add a lot). Moving
  goods takes a real vehicle trip: the buyer's cart drives to the source,
  loads, and returns over several ticks — goods arrive when it does, and
  the vehicle can't serve other orders meanwhile (throughput is a real
  constraint). Trip cost comes from the vehicle's modifier block (base +
  per-tick + per-tile + tiny weight/space terms), so hauling a full load
  costs nearly the same as hauling one unit. Everyone owns a porter (on
  foot, tiny basket) and a handcart; horse carts are the bulk tier.
  Vehicles burn fuel measured in demand points (a horse's hunger), fed
  from the owner's stock — an unfed vehicle refuses trips, except runs
  fetching its own feed. All buying compares *delivered* unit cost
  (price + trip/qty), and transfers between two parcels of the same owner
  cost no sale price but still need the trip. Trip coin goes to the
  village treasury and recirculates via the tithe.
- **Retail & warehouses.** Because the trip's base cost dominates, bulk
  buyers get goods at nearly producer price per unit while a single-unit
  fetch pays the full trip — that spread is the retail margin. General
  stores (small extra storage) and warehouses (huge) are reseller
  buildings: anything stocked on their parcel is for sale, restocked in
  bulk from producers automatically. NPCs build stores in neighbourhoods
  with no reseller nearby when the single-vs-bulk spread looks profitable,
  and buy horse carts when their trips keep hitting cargo capacity.
  Production machines stall ("full") when their parcel's storage is full.
- **The land market.** Unowned parcels can be bought for a fixed price (paid
  to the village). Owners can list spare, undeveloped parcels for sale and
  buy each other's. NPCs buy land when they want to build but are out of
  slots, and list idle extra parcels they've been too broke to develop.
- **Production & recipes.** Machines run a *chosen* recipe from their
  list (`content/RecipeDef/*.json`): a farm grows grain or raises horses;
  the workshop crafts handcarts, horse carts, and every machine kit.
  Manufacture time depends on the recipe AND the machine (rate +
  per-recipe overrides). Level `L` runs `2^(L-1)` batches per cycle.
  Owners restock inputs when buffers run low, by delivered cost.
- **Closed loop.** Machines and vehicles are products: building consumes
  the machine's kit from the parcel inventory; carts are commissioned
  from cart kits (a horse cart needs an actual farm-raised horse).
  Failed purchases record *unmet demand*, which is how workshops learn
  what to craft and farms learn when horses are wanted — and the player's
  "Request" button feeds the same signal. Entry points (grain, wood)
  need no inputs; everything else traces back to them.
- **Employment & the labor market.** Machines need operators and every
  cart trip needs a driver who rides along; one person does one thing at
  a time — the owner included. Skilled machines (baking, milling,
  carpentry…) need qualified operators, and mastery speeds machines up
  by each machine's `experience_rate` (a workshop rewards a veteran; a
  field doesn't much care). Skills come from paid training, from working
  the machine (XP/day), or by osmosis from workplace peers with
  different skills. Wages split on education and experience: each
  worker's reservation wage rises with mastery, sags with desperation,
  and is what they're actually paid; employers sponsor training when no
  qualified hands exist, and workers jump to operator-starved employers
  paying meaningfully more. Settlers arrive where the jobs are
  (parcels near short-staffed businesses — the seed of districts and
  towns), and the long-term jobless emigrate.
- **Seasonal foresight & manifests.** Planners read the calendar: input
  buffers and warehouse stock targets swell up to 3× heading into winter
  and run lean into summer, so pre-winter grain hoarding and seasonal
  price cycles emerge village-wide. Shipments carry manifests — several
  products from one source per trip, with shopping lists consolidated
  per parcel and one-stop sourcing that prefers a source covering more
  of the basket (the wholesale warehouse's reason to exist; resellers
  carry a cost basis and never price below it).
- **Prices.** All money is integer cents. NPC sellers do supply-demand
  price discovery in meaningful moves: sold out → raise ~10%; unsold
  stock → undercut the cheapest known competitor by ~2% (or cut ~7%);
  steady sales → hold. A recipe-cost floor keeps nobody selling below
  input cost; competition races prices toward cost in cent-level spreads.
  The player sets prices by the cent.
- **NPC investment.** Every 7 days (staggered per person) an NPC may make one
  move: *upgrade* a machine that actually runs (uptime ≥ 60%) and whose
  output kept selling out that week; *build* the best-margin machine if its
  primary output has no in-stock seller in their knowledge circle (a visible
  supply gap), buying the nearest available parcel first if they're out of
  room; or *list* an idle extra parcel for sale. Their market view is
  limited to who they know; build/upgrade coin goes to the village treasury
  and comes back out through the tithe.
- **Make-to-stock.** NPC machines pause when every output already has ~5
  days of observed sales in stock (or any output is grossly overstocked), so
  by-product demand can't pile mountains of the main product. Player
  machines never auto-pause.
- **Seasons & spoilage.** Seasonal recipes (grain) run ±25% faster/slower
  over a 48-day year, and perishables rot (~qty/shelf-life per day), so
  prices breathe: grain swings several-fold between harvest and winter,
  storage and timing matter, and stock targets respect shelf life.
  Sellers only raise prices when demand demonstrably went unserved —
  a rotting loaf "selling out" can't ratchet a famine. Business owners
  endure hard winters rather than abandon their machines.
- **The tithe.** A small daily % of everyone's coin — plus the treasury fed
  by construction, shipping, and common-land sales — is pooled and shared
  back equally. This is the MVP stand-in for wages. Total money in the world
  is exactly conserved (audited modulo migration, below).
- **Population dynamics.** Feeding people grows your market: while the
  village has food on the shelves (~3 days per head) and free land,
  settlers arrive — they buy a parcel, meet the neighbours, stockpile,
  and eventually open businesses through the normal investment logic.
  Anyone who goes meaningfully hungry day after day packs up and leaves,
  abandoning their machines and taking their coin with them. Settlers'
  starting coin is minted and emigrants' coin evaporates; both are
  tracked so the money audit still balances to the coin.

### Product chain

```
Wheat Farm ──> grain ──> Mill ──> flour ──> Bakery ──> bread (fulfills hunger)
                          └────> bran (by-product, cheap hunger fallback)
Woodcutter ──> wood ───────────────────────────┘ (bakery fuel)
```

## Playing

Click any parcel to inspect it (NPC businesses are view-only). On **your
parcels** (gold border) you can build machines in empty slots, upgrade them,
demolish them, and set sale prices with the +/- buttons. Unowned parcels show
a price tag — buy them to expand; spare empty parcels can be listed for sale.
NPCs will find you through the knowledge graph and buy what you sell.
`Space` pauses, `1/2/3` sets speed, `M` opens the market screen (traded
price history per product, volumes, stocks, your price vs the market, and
your net-worth/profit trendline), `K` toggles the knowledge-web overlay,
`F5`/`F9` save and load (`python run_game.py --load savegame.pkl` resumes),
`Esc` closes menus. The HUD tracks the season, population, your coin, net
worth, and yesterday's profit. The `a/A` toggle on each sale row delegates
that product's price to automatic daily discovery (the same AI the NPCs
use) — or keep it manual.

See [ROADMAP.md](ROADMAP.md) for where this is headed.

**Your unfair advantage:** your auto-buy (machine inputs and demand
purchases) sees every seller in the village, while NPCs only see the people
they know.

**Metrics:** every machine row shows its 7-day uptime; hover it (in the panel
or on the map) for yesterday's resource consumption/production. Hover a good
in *Goods for Sale* for yesterday's profit, units produced, units consumed by
the owner's own machines, and sales count. The home-parcel panel lists your
vehicles (status, fuel due, hover for cargo/cost/speed) with buy buttons, and
every parcel shows its storage gauge. Goods in transit appear on the map as
product-colored dots moving along their route.

## Code layout

| Path | What |
|---|---|
| `village/register.py` | Content registry (ported from the original project): scans content folders, validates JSON against Pydantic models |
| `village/objects.py` | Pydantic models for content (`ProductDef`, `MachineDef`, `DemandDef`, `VehicleDef` + the shared `Modifiers` block) |
| `content/<ModelName>/*.json` | The actual game content, one JSON file per definition |
| `content_custom/<mod>/` | Mod folders, loaded after `content/` so same-id definitions override |
| `village/content/` | Typed views (`PRODUCTS`, `MACHINES`, `DEMANDS`) the game code reads |
| `village/sim/` | The simulation: people, demands, vehicles/shipments, trade, machines, parcels, land market, world tick |
| `village/ui/` | pygame UI: map view, building panel, HUD, tooltips |
| `run_headless.py` | Run the economy with no UI and print health stats |

The sim has **no dependency on pygame** — `village/sim/` and
`village/content/` run headless, which is how the balance numbers in
`village/sim/config.py` were tuned.

Adding content is data-only: drop a JSON file into `content/ProductDef/`,
`content/MachineDef/`, `content/DemandDef/`, `content/VehicleDef/`, or
`content/AdvertisingDef/`
(folder name = Pydantic model class in `village/objects.py`). Mods in
`content_custom/` override by id.

## Art

All visuals are currently solid-color placeholder blocks. Real art can be
dropped into `assets/` file-by-file with no code changes — see
[ASSETS.md](ASSETS.md) for the full wishlist and file names.
