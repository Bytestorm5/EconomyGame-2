# Roadmap

Where this project could go next, roughly ordered by leverage. The "easy
wins" tier is implementable without structural change; the bigger items
each deserve a focused session.

## Easy wins (small/medium, no rewrites)

- **Demolish-to-kit.** Demolishing a machine should return a used kit
  (sellable at a discount) instead of conjuring refund coin from the
  treasury — closes the last "thin air" money path.
- **Player batch controls.** "Abort batch" button for stalled machines
  (NPCs already do this); pause/resume toggle per machine.
- **More demands.** The DemandDef system is fully data-driven but only
  hunger exists. A `warmth` demand (fulfilled by wood, winter-weighted via
  a `seasonal` contributor) would instantly create a second consumer
  market with opposite seasonality to grain. ~1 content file + one
  contributor key.
- **Per-product price memory on the market screen** — overlay your sale
  price history against the market line.
- **Sell orders / consignment.** Let the player push stock *to* a reseller
  (stores buy on the spot at a negotiated discount) instead of waiting to
  be discovered.
- **Event ticker.** A scrolling feed (sold X to Y, hired, spoiled, ad ran)
  — the data is all in the ledgers already.
- **Wage offers.** Per-employer wage instead of the flat config rate;
  scarce labor bids wages up — three-line change in `hire()` plus an NPC
  rule, and suddenly there's a labor *market*.

## Bigger changes worth a session each

1. ~~Multi-product trips~~ (done: manifests + one-stop sourcing).
   Remaining: NPC warehouse *viability* — wholesalers stay unprofitable
   without volume discounts or standing contracts, so worldgen doesn't
   seed one; the building is player-only in practice. Contracts (item 2)
   are the fix. (The once-noted hunger regression turned out to be a
   structural bread-capacity deficit; fixed by the 3-loaf bake recipe.)
1. **Multi-stop routing.** Carts currently haul one product per
   trip. Letting a trip carry a manifest (several products, several stops)
   would make logistics genuinely strategic and make warehouses hubs
   rather than big closets. This is the single highest-leverage change for
   the "logistics empire" fantasy.
2. **Contracts & standing orders.** Recurring agreements (N flour/day at a
   fixed price) between businesses. Stabilizes chains, creates negotiation
   gameplay, and gives the player B2B relationships to win. The unmet-
   demand plumbing is the natural foundation.
3. **A real labor market.** Wages set by supply/demand, employees who quit
   for better offers, skill levels that make veteran operators faster
   (feeds the `recipe_rates` hook that already exists).
4. **Seasonal foresight for NPCs.** Producers currently react to prices;
   letting them anticipate (stockpile grain before winter, as the player
   can) would deepen the seasonal economy — careful: herding risk, see the
   anti-herding note in world._choose_recipes.
5. **Banking & credit.** Loans against net worth (the bookkeeping already
   exists), interest, and bankruptcy/foreclosure — gives failing
   businesses an exit besides emigration and gives the player leverage.
6. **Towns & trade routes.** A second village with different resource
   endowments and a road between them: caravans, arbitrage, and the
   warehouse/courier business model at full scale. The world/parcel model
   generalizes; the knowledge graph would need locality weighting.
7. **Scenario/win conditions.** "Reach net worth X", "feed the village
   through 3 winters", "own the bread market" — the metrics to score all
   of these are already tracked.

## Known soft spots

- Seed-dependent fragility: bad geography can still produce lean villages
  (seed 123 runs hungry winters). The capital-anchor rule prevents
  collapse; a labor market and NPC foresight would fix the root cause.
- NPC expansion is conservative at default world size; growth gameplay
  shows best on `--blocks 4x3 --npcs 24+`.
- Old save files don't migrate across schema changes.
