import math

import pytest

from village.content import DEMANDS, load_all
from village.sim import config, demand, trade
from village.sim.machine import Machine
from village.sim.person import Person
from village.sim.plot import Plot
from village.sim.vehicle import Vehicle
from village.sim.world import World
from village.sim.worldgen import generate


@pytest.fixture(autouse=True)
def content():
    load_all()


def make_world():
    return World(60, 60, seed=1)


def make_person(world, pid, name, money, tile=(0, 0), is_player=False,
                vehicles=("porter", "handcart")):
    person = world.add_person(Person(pid, name, money, is_player=is_player))
    plot = world.add_plot(Plot(100 + pid, (tile[0], tile[1], 4, 4)))
    world.assign_plot(person, plot)
    for vid in vehicles:
        person.vehicles.append(Vehicle(vid))
    return person


def give_machine(world, person, def_id, plot=None):
    return world.build_machine(person, plot or person.home, def_id, free=True)


def settle(world, max_ticks=100):
    """Advance time until all shipments have arrived."""
    for _ in range(max_ticks):
        if not world.shipments:
            return
        world.tick_count += 1
        world._process_arrivals()
    raise AssertionError("shipments never settled")


def hunger():
    return DEMANDS.get("hunger")


# --- production ---------------------------------------------------------------

def test_machine_produces_after_cycle():
    world = make_world()
    owner = make_person(world, 0, "Miller", 100)
    mill = give_machine(world, owner, "mill")
    owner.add_items("grain", 4)
    for _ in range(mill.definition.cycle_ticks):
        mill.tick(owner)
    inv = owner.home.inventory
    assert inv["flour"] == 2
    assert inv["bran"] == 1
    assert inv["grain"] == 2  # consumed one cycle's worth


def test_level_doubles_throughput():
    world = make_world()
    owner = make_person(world, 0, "Miller", 100)
    mill = give_machine(world, owner, "mill")
    mill.level = 3  # 4 batches per cycle
    owner.add_items("grain", 100)
    for _ in range(mill.definition.cycle_ticks):
        mill.tick(owner)
    assert owner.stock("flour") == 8


def test_full_parcel_stalls_machine():
    world = make_world()
    owner = make_person(world, 0, "Farmer", 100)
    farm = give_machine(world, owner, "wheat_farm")
    owner.add_items("grain", 119)  # base capacity 120; output of 2 won't fit
    for _ in range(farm.definition.cycle_ticks):
        farm.tick(owner)
    assert farm.stalled
    assert owner.stock("grain") == 119
    owner.home.inventory["grain"] -= 10  # space frees up
    farm.tick(owner)
    assert not farm.stalled
    assert owner.stock("grain") == 111


def test_build_upgrade_demolish():
    world = make_world()
    person = make_person(world, 0, "P", 1000)
    plot = person.home

    m = world.build_machine(person, plot, "mill")
    assert m is not None and person.money == 1000 - 80
    assert world.upgrade_machine(person, m)
    assert m.level == 2 and m.max_batches == 2

    assert world.demolish_machine(person, plot, plot.slots.index(m))
    assert person.machines == [] and plot.machines() == []


# --- vehicles & trips -------------------------------------------------------------

def test_trip_math():
    v = Vehicle("handcart")  # speed 5, -0.05/wt; cost .5 + .05/tile + .0005*wt*tile
    dist = 10.0
    # 10 bread = 5 weight, 10 space
    assert v.max_qty("bread") == 20  # space-bound: 20 space / 1 per bread
    ticks = v.trip_ticks(dist, "bread", 10)
    assert ticks == math.ceil(10 / 5 + 10 / (5 - 0.05 * 5))
    cost = v.trip_cost(dist, "bread", 10)
    assert math.isclose(cost, 0.5 + 0.05 * 20 + 0.0005 * 5 * 10)
    fuel = v.trip_fuel(dist, "bread", 10)
    assert math.isclose(fuel, 0.25 * ticks)


def test_bulk_amortizes_trip_cost():
    """The retail premise: 10 units ship for almost the cost of 1."""
    world = make_world()
    buyer = make_person(world, 0, "B", 1000, tile=(0, 0),
                        vehicles=("handcart",))
    seller = make_person(world, 1, "S", 0, tile=(10, 0))
    give_machine(world, seller, "bakery")
    seller.add_items("bread", 20)
    trade.add_edge(world, buyer, seller)

    q1 = trade.best_quote(world, buyer, "bread", 1, buyer.home)
    q10 = trade.best_quote(world, buyer, "bread", 10, buyer.home)
    ship1 = q1.unit_cost - q1.offer.price
    ship10 = q10.unit_cost - q10.offer.price
    assert ship10 < ship1 / 4  # near-flat trip cost spread over the load


def test_delivered_cost_beats_sticker_price():
    """A $3 product + $2 trip outperforms a $2 product + $5 trip."""
    world = make_world()
    buyer = make_person(world, 0, "B", 100, tile=(0, 0),
                        vehicles=("handcart",))
    near = make_person(world, 1, "Near", 0, tile=(10, 0))
    far = make_person(world, 2, "Far", 0, tile=(40, 0))
    for seller, price in ((near, 3), (far, 2)):
        give_machine(world, seller, "bakery")
        seller.add_items("bread", 5)
        seller.prices["bread"] = price
        trade.add_edge(world, buyer, seller)

    assert trade.buy(world, buyer, "bread", qty=1) == 1
    assert near.money == 3 and far.money == 0  # near won despite price
    assert buyer.money == 100 - 3 - 2          # $2 trip (ceil of 1.5)
    settle(world)
    assert buyer.stock("bread") == 1


def test_transit_takes_time_and_occupies_vehicle():
    world = make_world()
    buyer = make_person(world, 0, "B", 100, tile=(0, 0),
                        vehicles=("handcart",))
    seller = make_person(world, 1, "S", 0, tile=(20, 0))
    give_machine(world, seller, "bakery")
    seller.add_items("bread", 10)
    trade.add_edge(world, buyer, seller)

    assert trade.buy(world, buyer, "bread", qty=4) == 4
    # Goods left the seller and money moved instantly...
    assert seller.stock("bread") == 6
    assert seller.money > 0
    # ...but nothing has arrived yet and the cart is out.
    assert buyer.stock("bread") == 0
    assert not buyer.vehicles[0].idle(world.tick_count)
    assert buyer.inbound_total("bread") == 4
    # A second buy finds no idle vehicle.
    assert trade.buy(world, buyer, "bread", qty=1) == 0

    settle(world)
    assert buyer.stock("bread") == 4
    assert buyer.inbound_total("bread") == 0
    assert buyer.vehicles[0].idle(world.tick_count)


def test_internal_transfer_free_goods_paid_trip():
    world = make_world()
    owner = make_person(world, 0, "Owner", 100, tile=(0, 0),
                        vehicles=("porter",))
    depot = world.add_plot(Plot(50, (20, 0, 4, 4)))
    world.assign_plot(owner, depot)
    depot.inventory["grain"] += 10

    got = trade.buy(world, owner, "grain", qty=5, dest=owner.home)
    assert got == 5
    settle(world)
    assert owner.home.inventory["grain"] == 5
    assert depot.inventory["grain"] == 5
    # porter: ceil(0.1 + 0.02 * 40) = 1 coin, no sale price
    assert owner.money == 99
    assert world.treasury == 1
    assert world.stats.trades == 0  # not a sale


def test_storage_cap_limits_orders():
    world = make_world()
    buyer = make_person(world, 0, "B", 1000, tile=(0, 0))
    seller = make_person(world, 1, "S", 0, tile=(10, 0))
    give_machine(world, seller, "wheat_farm")
    seller.add_items("grain", 500)
    trade.add_edge(world, buyer, seller)
    buyer.home.inventory["grain"] = 100  # base capacity 120

    got = trade.buy(world, buyer, "grain", qty=50)
    assert got <= 20  # whatever fits, never over capacity
    settle(world)
    uw, _ = buyer.home.used()
    cw, _ = buyer.home.capacity()
    assert uw <= cw


def test_fuel_accrues_blocks_and_feeds():
    world = make_world()
    person = make_person(world, 0, "Carter", 100, vehicles=("handcart",))
    cart = person.vehicles[0]
    cart.fuel_due = 30.0
    assert cart.blocked

    # Feeding from stock: bran fulfills 8 hunger points each. Eats only
    # whole units' worth of debt (30 -> 3 bran -> 6 points carry over).
    person.add_items("bran", 5)
    world._feed_vehicles(person)
    assert cart.fuel_due == pytest.approx(6.0)
    assert person.stock("bran") == 2
    assert not cart.blocked


def test_blocked_vehicle_still_runs_feed_errands():
    world = make_world()
    buyer = make_person(world, 0, "B", 100, tile=(0, 0),
                        vehicles=("handcart",))
    cart = buyer.vehicles[0]
    cart.fuel_due = 50.0
    seller = make_person(world, 1, "S", 0, tile=(10, 0))
    give_machine(world, seller, "mill")
    seller.add_items("bran", 10)
    seller.add_items("flour", 10)
    trade.add_edge(world, buyer, seller)

    # Normal goods: refused. Feed for its own fuel demand: allowed.
    assert trade.buy(world, buyer, "flour", qty=2) == 0
    assert trade.buy(world, buyer, "bran", qty=2, feed_run=True) == 2


# --- retail --------------------------------------------------------------------

def test_reseller_sells_unproduced_goods():
    world = make_world()
    grocer = make_person(world, 0, "Grocer", 500)
    assert not grocer.sells("bread")  # nothing produced, nothing resold
    give_machine(world, grocer, "general_store")
    grocer.add_items("bread", 10)
    assert grocer.sells("bread")      # stocked on a reseller parcel
    # Store storage raises the parcel's capacity.
    cw, cs = grocer.home.capacity()
    assert cw == config.BASE_PARCEL_STORAGE_WEIGHT + 250


def test_store_restocks_from_producers_only():
    world = make_world()
    grocer = make_person(world, 0, "Grocer", 500, tile=(0, 0))
    give_machine(world, grocer, "general_store")
    baker = make_person(world, 1, "Baker", 0, tile=(10, 0))
    give_machine(world, baker, "bakery")
    baker.add_items("bread", 40)
    rival = make_person(world, 2, "Rival", 0, tile=(4, 0))
    give_machine(world, rival, "general_store")
    rival.add_items("bread", 40)  # closer, but a reseller
    trade.add_edge(world, grocer, baker)
    trade.add_edge(world, grocer, rival)

    world._restock(grocer)
    settle(world)
    assert baker.stats_today and baker.stat("bread").sold > 0
    assert rival.stat("bread").sold == 0


# --- knowledge & referrals ----------------------------------------------------------

def test_referral_forms_new_edge():
    world = make_world()
    buyer = make_person(world, 0, "Buyer", 100, tile=(0, 0))
    friend = make_person(world, 1, "Friend", 0, tile=(6, 0))
    baker = make_person(world, 2, "Baker", 0, tile=(12, 0))
    trade.add_edge(world, buyer, friend)
    trade.add_edge(world, friend, baker)
    world.stats.edges_formed = 0
    give_machine(world, baker, "bakery")
    baker.add_items("bread", 5)

    assert trade.buy(world, buyer, "bread") == 1
    assert baker.id in buyer.knowledge
    assert world.stats.edges_formed == 1


def test_player_autobuy_knows_everyone():
    world = make_world()
    player = make_person(world, 0, "You", 100, tile=(0, 0), is_player=True)
    world.player_id = 0
    hermit = make_person(world, 1, "Hermit", 0, tile=(8, 0))
    give_machine(world, hermit, "bakery")
    hermit.add_items("bread", 3)
    # No knowledge edge at all -- an NPC buyer would need a lucky referral,
    # but the player's auto-buy sees the whole market.
    assert trade.buy(world, player, "bread") == 1
    npc = make_person(world, 2, "Npc", 100, tile=(16, 0))
    assert trade.buy(world, npc, "bread") == 0  # knows nobody, no referral


# --- seller AI -------------------------------------------------------------------

def test_supply_demand_pricing():
    world = make_world()
    person = make_person(world, 0, "Baker", 100)
    give_machine(world, person, "bakery")
    person.prices["bread"] = 10

    # Sold out -> price rises.
    person.stat("bread").sold = 5
    person.adjust_prices_daily()
    assert person.prices["bread"] > 10

    # Stock but no sales -> price falls.
    person.prices["bread"] = 10
    person.stats_today = {}
    person.add_items("bread", 8)
    person.adjust_prices_daily()
    assert person.prices["bread"] < 10

    # Selling steadily with stock left -> hold.
    person.prices["bread"] = 10
    person.stats_today = {}
    person.stat("bread").sold = 3
    person.adjust_prices_daily()
    assert person.prices["bread"] == 10


def test_trade_records_ledger_and_uptime():
    world = make_world()
    buyer = make_person(world, 0, "Buyer", 100, tile=(0, 0),
                        vehicles=("porter",))
    seller = make_person(world, 1, "Seller", 0, tile=(10, 0))
    farm = give_machine(world, seller, "wheat_farm")
    seller.add_items("grain", 5)
    seller.prices["grain"] = 2
    trade.add_edge(world, buyer, seller)
    trade.buy(world, buyer, "grain", qty=3)

    assert seller.stat("grain").sold == 3
    assert seller.stat("grain").revenue == 6
    trip = math.ceil(0.1 + 0.02 * 20)  # porter round trip, 10 tiles
    assert buyer.stat("grain").spent == 6 + trip

    for _ in range(farm.definition.cycle_ticks):
        farm.tick(seller)
    assert farm.uptime() == 1.0  # ran every tick so far today
    assert seller.stat("grain").produced == 2

    seller.end_of_day()
    day = seller.yesterday("grain")
    assert day.sold == 3 and day.produced == 2 and day.stock_end == 4
    assert farm.history[-1].uptime == 1.0
    assert farm.history[-1].produced == {"grain": 2}


# --- land market -------------------------------------------------------------------

def test_buy_unowned_parcel():
    world = make_world()
    person = make_person(world, 0, "P", 500)
    empty = world.add_plot(Plot(50, (10, 0, 4, 4)))
    assert world.plot_sale_price(empty) == config.PARCEL_PRICE
    assert world.buy_plot(person, empty)
    assert empty.owner_id == person.id
    assert person.money == 500 - config.PARCEL_PRICE
    assert world.treasury == config.PARCEL_PRICE  # common land -> village
    assert len(person.plots) == 2


def test_list_and_buy_between_people():
    world = make_world()
    seller = make_person(world, 0, "S", 0)
    extra = world.add_plot(Plot(50, (10, 0, 4, 4)))
    world.assign_plot(seller, extra)
    buyer = make_person(world, 1, "B", 500)

    assert not world.list_plot(seller, seller.home)  # can't sell home
    assert world.list_plot(seller, extra)
    assert world.buy_plot(buyer, extra)
    assert extra.owner_id == buyer.id
    assert seller.money == config.PARCEL_PRICE
    assert extra not in seller.plots and extra in buyer.plots


def test_npc_expands_onto_new_parcel():
    world = make_world()
    # (day=1 + id=6) % INVEST_PERIOD_DAYS(7) == 0 -> invests today.
    npc = make_person(world, 6, "Rich", 1000, tile=(0, 0))
    give_machine(world, npc, "woodcutter")
    give_machine(world, npc, "woodcutter")     # home full (2 slots)
    world.add_plot(Plot(50, (10, 0, 4, 4)))    # unowned land available
    assert npc.home.free_slot() is None

    world._consider_investment(npc)
    assert len(npc.plots) == 2                 # bought the expansion parcel


def test_npc_lists_idle_parcel_when_broke():
    world = make_world()
    npc = make_person(world, 6, "Broke", 30, tile=(0, 0))
    extra = world.add_plot(Plot(50, (10, 0, 4, 4)))
    world.assign_plot(npc, extra)
    world.tick_count = 14 * config.TICKS_PER_DAY  # day 15; (15+6)%7 == 0
    extra.acquired_day = 0

    world._consider_investment(npc)
    assert extra.for_sale_price == config.PARCEL_PRICE


# --- demands ------------------------------------------------------------------------

def test_demand_accumulates_and_consumes_reserves():
    world = make_world()
    person = make_person(world, 0, "Eater", 100)
    person.add_items("bread", 2)
    for _ in range(hunger().urgency.want):
        demand.tick(world, person)
    # On reaching "want" they ate from home reserves.
    assert person.stock("bread") == 1
    assert person.demands["hunger"] < hunger().urgency.want


def test_demand_purchase_is_an_order_and_sets_loyalty():
    world = make_world()
    eater = make_person(world, 0, "Eater", 100, tile=(0, 0))
    baker = make_person(world, 1, "Baker", 0, tile=(8, 0))
    give_machine(world, baker, "bakery")
    baker.add_items("bread", 5)
    trade.add_edge(world, eater, baker)

    eater.demands["hunger"] = float(hunger().urgency.want)
    assert demand.fulfill(world, eater, hunger(), urgent=False)
    assert eater.demand_memory["hunger"] == (baker.id, "bread")
    assert baker.money > 0
    assert eater.stock("bread") == 0          # still on the cart
    assert eater.inbound_total("bread") > 0
    # While the order is en route they wait instead of double-buying.
    assert not demand.fulfill(world, eater, hunger(), urgent=True)
    assert eater.unfulfilled.get("hunger", 0) == 0

    settle(world)
    assert eater.stock("bread") > 0
    assert demand.fulfill(world, eater, hunger(), urgent=False)  # eats


def test_want_stage_respects_delivered_price_tolerance():
    world = make_world()
    eater = make_person(world, 0, "Eater", 1000, tile=(0, 0))
    baker = make_person(world, 1, "Gouger", 0, tile=(8, 0))
    give_machine(world, baker, "bakery")
    baker.add_items("bread", 5)
    baker.prices["bread"] = 99  # way above tolerance
    trade.add_edge(world, eater, baker)

    eater.demands["hunger"] = float(hunger().urgency.want)
    assert not demand.fulfill(world, eater, hunger(), urgent=False)
    assert demand.fulfill(world, eater, hunger(), urgent=True)  # any cost
    assert baker.money >= 99


# --- whole-world ----------------------------------------------------------------------

def test_world_runs_and_conserves_money():
    world = generate(seed=99)
    total_before = sum(p.money for p in world.people.values()) + world.treasury
    world.run_days(10)
    total_after = sum(p.money for p in world.people.values()) + world.treasury
    assert total_before == total_after
    assert world.stats.trades > 0
    assert world.stats.trips >= world.stats.trades


def test_configurable_worldgen():
    world = generate(seed=1, blocks=(4, 3), npcs=20)
    assert len(world.plots) == 48
    assert len(world.people) == 21
    for p in world.people.values():
        assert len(p.vehicles) == len(config.STARTING_VEHICLES)
    # The starter mix includes at least one retailer.
    assert any(pl.resells() for pl in world.plots.values())
    with pytest.raises(ValueError):
        generate(seed=1, blocks=(1, 1), npcs=10)  # 4 parcels < 11 people
