import pytest

from village.content import load_all
from village.sim import config, demand, trade
from village.sim.machine import Machine
from village.sim.person import Person
from village.sim.plot import Plot
from village.sim.world import World
from village.sim.worldgen import generate


@pytest.fixture(autouse=True)
def content():
    load_all()


def make_world():
    return World(60, 60, seed=1)


def make_person(world, pid, name, money, tile=(0, 0), is_player=False):
    person = world.add_person(Person(pid, name, money, is_player=is_player))
    plot = world.add_plot(Plot(100 + pid, (tile[0], tile[1], 4, 4)))
    world.assign_plot(person, plot)
    return person


def give_machine(world, person, def_id, plot=None):
    return world.build_machine(person, plot or person.home, def_id, free=True)


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


def test_machine_idle_without_inputs():
    world = make_world()
    owner = make_person(world, 0, "Miller", 100)
    mill = give_machine(world, owner, "mill")
    for _ in range(20):
        mill.tick(owner)
    assert owner.stock("flour") == 0


def test_level_doubles_throughput():
    world = make_world()
    owner = make_person(world, 0, "Miller", 100)
    mill = give_machine(world, owner, "mill")
    mill.level = 3  # 4 batches per cycle
    owner.add_items("grain", 100)
    for _ in range(mill.definition.cycle_ticks):
        mill.tick(owner)
    assert owner.stock("flour") == 8


def test_build_upgrade_demolish():
    world = make_world()
    person = make_person(world, 0, "P", 1000)
    plot = person.home

    m = world.build_machine(person, plot, "mill")
    assert m is not None and person.money == 1000 - 80
    assert m.plot is plot
    assert world.upgrade_machine(person, m)
    assert m.level == 2 and m.max_batches == 2

    assert world.demolish_machine(person, plot, plot.slots.index(m))
    assert person.machines == [] and plot.machines() == []


# --- trading & shipping ---------------------------------------------------------

def test_buy_from_cheapest_known_seller():
    world = make_world()
    buyer = make_person(world, 0, "Buyer", 100, tile=(0, 0))
    # Equidistant sellers so only price differs.
    cheap = make_person(world, 1, "Cheap", 0, tile=(10, 0))
    dear = make_person(world, 2, "Dear", 0, tile=(0, 10))
    for seller, price in ((cheap, 4), (dear, 9)):
        give_machine(world, seller, "bakery")
        seller.add_items("bread", 5)
        seller.prices["bread"] = price
        trade.add_edge(world, buyer, seller)

    assert trade.buy(world, buyer, "bread", qty=2) == 2
    assert cheap.money == 8 and dear.money == 0
    assert buyer.stock("bread") == 2


def test_shipping_beats_sticker_price():
    """A $3 product + $1 shipping outperforms a $2 product + $3 shipping."""
    world = make_world()
    buyer = make_person(world, 0, "Buyer", 100, tile=(0, 0))
    near = make_person(world, 1, "Near", 0, tile=(10, 0))    # 10 tiles -> $1/u
    far = make_person(world, 2, "Far", 0, tile=(30, 0))      # 30 tiles -> $3/u
    for seller, price in ((near, 3), (far, 2)):
        give_machine(world, seller, "bakery")
        seller.add_items("bread", 5)
        seller.prices["bread"] = price
        trade.add_edge(world, buyer, seller)

    assert trade.buy(world, buyer, "bread", qty=1) == 1
    assert near.money == 3 and far.money == 0     # near won despite price
    assert world.stats.shipping_paid == 1
    assert buyer.money == 100 - 3 - 1


def test_internal_transfer_free_goods_paid_shipping():
    world = make_world()
    owner = make_person(world, 0, "Owner", 100, tile=(0, 0))
    depot = world.add_plot(Plot(50, (20, 0, 4, 4)))  # 20 tiles -> $2/u ship
    world.assign_plot(owner, depot)
    depot.inventory["grain"] += 10

    got = trade.buy(world, owner, "grain", qty=5, dest=owner.home)
    assert got == 5
    assert owner.home.inventory["grain"] == 5
    assert depot.inventory["grain"] == 5
    assert owner.money == 100 - 10  # ceil(5 * 20 * 0.1), no sale price
    assert world.stats.trades == 0  # not a sale
    assert world.treasury == 10


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
    buyer = make_person(world, 0, "Buyer", 100, tile=(0, 0))
    seller = make_person(world, 1, "Seller", 0, tile=(10, 0))
    farm = give_machine(world, seller, "wheat_farm")
    seller.add_items("grain", 5)
    seller.prices["grain"] = 2
    trade.add_edge(world, buyer, seller)
    trade.buy(world, buyer, "grain", qty=3)

    assert seller.stat("grain").sold == 3
    assert seller.stat("grain").revenue == 6
    assert buyer.stat("grain").spent == 6 + 3  # incl. 3u x 10 tiles shipping

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


def test_cannot_list_developed_parcel():
    world = make_world()
    person = make_person(world, 0, "P", 500)
    extra = world.add_plot(Plot(50, (10, 0, 4, 4)))
    world.assign_plot(person, extra)
    world.build_machine(person, extra, "wheat_farm", free=True)
    assert not world.list_plot(person, extra)


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
    world.tick_count = 15 * config.TICKS_PER_DAY  # day 16; (16+6)%7 has...
    world.tick_count = 14 * config.TICKS_PER_DAY  # day 15; (15+6)%7 == 0
    extra.acquired_day = 0

    world._consider_investment(npc)
    assert extra.for_sale_price == config.PARCEL_PRICE


# --- demands ------------------------------------------------------------------------

def test_demand_accumulates_and_consumes_reserves():
    world = make_world()
    person = make_person(world, 0, "Eater", 100)
    person.add_items("bread", 2)
    hunger = next(d for d in __import__(
        "village.content", fromlist=["DEMANDS"]).DEMANDS if d.id == "hunger")

    for _ in range(hunger.urgency.want):
        demand.tick(world, person)
    # On reaching "want" they ate from home reserves.
    assert person.stock("bread") == 1
    assert person.demands["hunger"] < hunger.urgency.want


def test_demand_purchase_sets_loyalty_memory():
    world = make_world()
    eater = make_person(world, 0, "Eater", 100, tile=(0, 0))
    baker = make_person(world, 1, "Baker", 0, tile=(8, 0))
    give_machine(world, baker, "bakery")
    baker.add_items("bread", 5)
    trade.add_edge(world, eater, baker)

    hunger = next(d for d in __import__(
        "village.content", fromlist=["DEMANDS"]).DEMANDS if d.id == "hunger")
    eater.demands["hunger"] = hunger.urgency.want
    assert demand.fulfill(world, eater, hunger, urgent=False)
    assert eater.demand_memory["hunger"] == (baker.id, "bread")
    assert baker.money > 0


def test_want_stage_respects_price_tolerance():
    world = make_world()
    eater = make_person(world, 0, "Eater", 1000, tile=(0, 0))
    baker = make_person(world, 1, "Gouger", 0, tile=(8, 0))
    give_machine(world, baker, "bakery")
    baker.add_items("bread", 5)
    baker.prices["bread"] = 99  # way above tolerance
    trade.add_edge(world, eater, baker)

    hunger = next(d for d in __import__(
        "village.content", fromlist=["DEMANDS"]).DEMANDS if d.id == "hunger")
    eater.demands["hunger"] = hunger.urgency.want
    assert not demand.fulfill(world, eater, hunger, urgent=False)
    assert demand.fulfill(world, eater, hunger, urgent=True)  # need: any cost
    assert baker.money == 99


# --- whole-world ----------------------------------------------------------------------

def test_world_runs_and_conserves_money():
    world = generate(seed=99)
    total_before = sum(p.money for p in world.people.values()) + world.treasury
    world.run_days(10)
    total_after = sum(p.money for p in world.people.values()) + world.treasury
    assert total_before == total_after
    assert world.stats.trades > 0


def test_configurable_worldgen():
    world = generate(seed=1, blocks=(4, 3), npcs=20)
    assert len(world.plots) == 48
    assert len(world.people) == 21
    unowned = sum(1 for p in world.plots.values() if p.owner_id is None)
    assert unowned == 48 - 21
    with pytest.raises(ValueError):
        generate(seed=1, blocks=(1, 1), npcs=10)  # 4 parcels < 11 people
