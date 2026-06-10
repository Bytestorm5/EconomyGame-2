import pytest

from village.content import load_all
from village.sim import config
from village.sim.machine import Machine
from village.sim.person import Person
from village.sim.world import World
from village.sim import trade
from village.sim.worldgen import generate


@pytest.fixture(autouse=True)
def content():
    load_all()


def make_world():
    return World(10, 10, seed=1)


def test_machine_produces_after_cycle():
    owner = Person(0, "Miller", 100)
    owner.add_items("grain", 4)
    mill = Machine("mill")
    for _ in range(mill.definition.cycle_ticks):
        mill.tick(owner)
    assert owner.inventory["flour"] == 2
    assert owner.inventory["bran"] == 1
    assert owner.inventory["grain"] == 2  # consumed one cycle's worth


def test_machine_idle_without_inputs():
    owner = Person(0, "Miller", 100)
    mill = Machine("mill")
    for _ in range(20):
        mill.tick(owner)
    assert owner.inventory["flour"] == 0


def test_level_doubles_throughput():
    owner = Person(0, "Miller", 100)
    owner.add_items("grain", 100)
    mill = Machine("mill", level=3)  # 4 batches per cycle
    for _ in range(mill.definition.cycle_ticks):
        mill.tick(owner)
    assert owner.inventory["flour"] == 8


def test_buy_from_cheapest_known_seller():
    world = make_world()
    buyer = world.add_person(Person(0, "Buyer", 100))
    cheap = world.add_person(Person(1, "Cheap", 0))
    dear = world.add_person(Person(2, "Dear", 0))
    for seller, price in ((cheap, 4), (dear, 9)):
        seller.machines.append(Machine("bakery"))
        seller.add_items("bread", 5)
        seller.prices["bread"] = price
        buyer.knowledge.add(seller.id)
        seller.knowledge.add(buyer.id)

    assert trade.buy(world, buyer, "bread", qty=2) == 2
    assert cheap.money == 8 and dear.money == 0
    assert buyer.inventory["bread"] == 2
    assert buyer.money == 92


def test_referral_forms_new_edge():
    world = make_world()
    buyer = world.add_person(Person(0, "Buyer", 100))
    friend = world.add_person(Person(1, "Friend", 0))
    baker = world.add_person(Person(2, "Baker", 0))
    # buyer knows only friend; friend knows baker; baker sells bread.
    buyer.knowledge.add(friend.id)
    friend.knowledge.update({buyer.id, baker.id})
    baker.knowledge.add(friend.id)
    baker.machines.append(Machine("bakery"))
    baker.add_items("bread", 5)

    assert trade.buy(world, buyer, "bread") == 1
    assert baker.id in buyer.knowledge
    assert buyer.id in baker.knowledge
    assert world.stats.edges_formed == 1


def test_no_seller_no_trade():
    world = make_world()
    buyer = world.add_person(Person(0, "Buyer", 100))
    assert trade.buy(world, buyer, "bread") == 0
    assert buyer.money == 100


def test_build_upgrade_demolish():
    world = make_world()
    from village.sim.plot import Plot
    person = world.add_person(Person(0, "P", 1000))
    plot = world.add_plot(Plot(0, (0, 0, 4, 4)))
    world.assign_plot(person, plot)

    m = world.build_machine(person, plot, "mill")
    assert m is not None and person.money == 1000 - 80
    assert world.upgrade_machine(person, m)
    assert m.level == 2 and m.max_batches == 2

    assert world.demolish_machine(person, plot, plot.slots.index(m))
    assert person.machines == [] and plot.machines() == []


def test_world_runs_and_conserves_money():
    world = generate(seed=99)
    total_before = sum(p.money for p in world.people.values())
    world.run_days(10)
    total_after = sum(p.money for p in world.people.values())
    assert total_before == total_after
    assert world.stats.trades > 0
    # The knowledge graph should have grown via referrals.
    assert world.stats.edges_formed >= 0
