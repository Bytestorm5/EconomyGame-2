"""Tunable simulation constants."""

# Time
TICKS_PER_DAY = 24

# World layout (defaults; override via CLI flags on run_game/run_headless).
# The village is a grid of blocks separated by roads; each block holds a
# 2x2 group of 4x4-tile parcels.
BLOCKS_X = 3
BLOCKS_Y = 2
NPC_COUNT = 14

# Parcels
PARCEL_PRICE = 15000        # cents; fixed price for unowned parcels/listings
PARCEL_IDLE_DAYS = 14       # NPC lists an empty extra parcel after this long
                            # if too broke to develop it
# Base storage of a bare parcel; reseller buildings add their own on top.
BASE_PARCEL_STORAGE_WEIGHT = 120.0
BASE_PARCEL_STORAGE_SPACE = 120.0

# Vehicles & logistics (costs/speeds live in content/VehicleDef/*.json)
STARTING_VEHICLES = ["porter", "handcart"]  # everyone begins with these
FUEL_BLOCK_THRESHOLD = 24.0     # fuel-demand points of debt before a vehicle
                                # refuses new trips (except feed runs)
FEED_BUFFER_POINTS = 24.0       # extra feed bought beyond current debt
DEMAND_BUY_DAYS = 2.0           # consumers buy this many days of a demand
                                # per trip (amortizes the trip's base cost)
NPC_MAX_VEHICLES = 3
NPC_VEHICLE_UPGRADE = "horse_cart"
CAPPED_TRIPS_FOR_UPGRADE = 5    # capacity-capped trips before an NPC buys it

# Retail heuristics
STORE_GAP_RADIUS = 12.0         # NPC builds a store only if no reseller
                                # parcel sits within this radius of home
STORE_EXPECTED_DAILY_SALES = 3  # per carried product, for margin estimates

# Demands (see content/DemandDef/*.json for the demands themselves)
DEMAND_CAP_FACTOR = 2.0     # demand points cap at need * this
WANT_PRICE_TOLERANCE = 2.0  # at "want" urgency, max delivered price as a
                            # multiple of the product's base price
# Knowledge-graph referral search
REFERRAL_CONTINUE_PROB = 0.6   # chance of recursing one hop deeper, ** depth
REFERRAL_MAX_DEPTH = 6

# Knowledge-graph dynamics (1 tick = 1 hour)
FORGET_PROB = 0.002         # per tick, per known *seller*, unless the person
                            # bought from that seller this very tick
MIN_KNOWLEDGE = 2           # never forget below this many acquaintances
AD_FATIGUE_THRESHOLD = 3    # hear of a seller more than this -> intentional
                            # forget; fatigue fades via the forget flow
AD_BUDGET_FACTOR = 4        # NPCs advertise only with cost * this in coin
NPC_AD_PERIOD_DAYS = 3      # NPCs weigh a campaign this often (staggered);
                            # without restraint they spam the village into
                            # fatigue and everyone intentionally forgets them
AD_DISCOURAGED_DAYS = 14    # after a campaign that moved no product, an NPC
                            # gives up on advertising for this long

# Personal stockpile: a person will not let themselves starve if they can
# help it -- they keep this many days of every demand at home, topping it
# up daily before hunger ever bites.
PERSONAL_STOCKPILE_DAYS = 3.0
STOCKPILE_TRIGGER_DAYS = 1.0  # top up only when below this -- fewer,
                              # bigger trips so machines keep running

# Production / trading
RESTOCK_TRIGGER = 0.5       # reorder inputs/stock when below this fraction
INPUT_BUFFER_DAYS = 3.0     # owners stock this many days of machine inputs
MACHINE_MAX_LEVEL = 5
UPGRADE_COST_FACTOR = 3     # upgrade L -> L+1 costs build_cost * factor**L
DEMOLISH_REFUND = 0.5

# NPC daily price discovery (supply & demand as the seller observes it).
# Prices move in meaningful percentage steps at cent granularity -- and a
# seller whose stock isn't moving undercuts the cheapest competitor they
# know of instead of slowly decaying.
PRICE_UP_FACTOR = 1.10      # sold out today -> raise (min +5 cents)
PRICE_DOWN_FACTOR = 0.93    # nothing sold today (with stock) -> lower
UNDERCUT_FRAC = 0.02        # price just below a known competitor
RESALE_MARKUP = 1.25        # resellers' baseline over acquisition cost
PRICE_MIN = 1               # one cent

# Bookkeeping window for metrics and AI decisions (sim days)
STATS_WINDOW_DAYS = 7

# Demand-aware production (make-to-stock, NPCs only): a machine pauses while
# every output's stock exceeds STOCK_TARGET_DAYS worth of that seller's
# recent daily sales (at least STOCK_TARGET_MIN units).
STOCK_TARGET_DAYS = 5
STOCK_TARGET_MIN = 10
STOCK_HARD_CAP_FACTOR = 5   # pause if ANY output exceeds target by this much

# NPC investment heuristic: every INVEST_PERIOD_DAYS (staggered per person)
# an NPC may make one move -- upgrade a busy machine whose output keeps
# selling out, build the machine with the best estimated margin given the
# prices they personally know about, or buy a parcel to expand onto.
INVEST_PERIOD_DAYS = 7
INVEST_RESERVE_FACTOR = 2.5   # must hold cost * this in coin to invest
INVEST_MIN_UPTIME = 0.6       # only upgrade machines that actually run
INVEST_SELLOUT_DAYS = 3       # sold-out days in window to justify an upgrade

# Village tithe: daily % of everyone's coin pooled and redistributed equally.
# This is the MVP stand-in for wages -- without it, money drains one-way up
# the production chain and consumers go broke.
TITHE_RATE = 0.05

# Population dynamics: prosperity attracts settlers; chronic hunger drives
# people away. Immigrants' starting coin is minted (the money supply grows
# with population); emigrants' coin evaporates with them.
IMMIGRATION_PROB = 0.15       # per day, while the village looks prosperous
IMMIGRATION_FOOD_DAYS = 3.0   # stocked food (days/head) that reads as plenty
HUNGRY_DAY_TICKS = 4          # unmet-need ticks that mark a day as "hungry"
EMIGRATE_HUNGRY_DAYS = 10     # hungry days in a row before someone leaves
MIN_POPULATION = 6            # nobody emigrates from a dying hamlet

# Employment: machines and vehicles need operators. The owner counts as
# one worker; beyond that, citizens are hired at a flat daily wage.
WAGE_PER_DAY = 800          # cents/day
LABORER_FRACTION = 0.6      # extra jobless citizens seeded per business owner
HIRE_NO_STAFF_TICKS = 4     # unmanned machine-ticks/day before NPCs hire

# Closed-loop building: kits on order are remembered this long before the
# NPC gives up on the plan.
PENDING_KIT_DAYS = 14
STOCK_TARGET_MIN_HEAVY = 2  # make-to-stock floor for heavy goods (kits,
                            # vehicles, livestock) instead of STOCK_TARGET_MIN

# Seasons: seasonal recipes (field work) swing between these rates over a
# year -- harvests are cheap in summer, dear in winter, and storage pays.
YEAR_DAYS = 48
SEASON_AMPLITUDE = 0.25     # rate = 1 +/- this over the year
FORESIGHT_DAYS = 10         # how far ahead producers/stockists look
FORESIGHT_MAX_MULT = 3.0    # buffer multiplier heading into scarcity
ONE_STOP_TOLERANCE = 0.35   # pay up to this much more per unit for a source
                            # that also covers the rest of the shopping list

# Player-facing market data
MARKET_HISTORY_DAYS = 120

# Starting conditions
NPC_START_MONEY = 20000     # cents
PLAYER_START_MONEY = 40000  # cents
PLOT_SLOTS = 2
