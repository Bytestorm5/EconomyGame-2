"""Tunable simulation constants."""

# Time
TICKS_PER_DAY = 24

# Hunger / eating
HUNGER_PER_TICK = 1
EAT_THRESHOLD = 16          # start looking for food at this hunger
HUNGER_MAX = 100
HUNGER_PER_FOOD_VALUE = 8   # eating reduces hunger by food_value * this
# Order in which hungry people try foods (best first, cheap fallback last).
FOOD_PREFERENCE = ["bread", "bran"]

# Knowledge-graph referral search
REFERRAL_CONTINUE_PROB = 0.6   # chance of recursing one hop deeper, ** depth
REFERRAL_MAX_DEPTH = 6

# Production / trading
INPUT_BUFFER_DAYS = 1.5     # owners stock this many days of machine inputs
MACHINE_MAX_LEVEL = 5
UPGRADE_COST_FACTOR = 3     # upgrade L -> L+1 costs build_cost * factor**L
DEMOLISH_REFUND = 0.5

# NPC daily price discovery (supply & demand as the seller observes it)
PRICE_UP_FACTOR = 1.15      # sold out today -> raise
PRICE_DOWN_FACTOR = 0.9     # nothing sold today (with stock) -> lower
PRICE_MIN = 1

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
# selling out, or build the machine with the best estimated margin given the
# prices they personally know about.
INVEST_PERIOD_DAYS = 7
INVEST_RESERVE_FACTOR = 2.5   # must hold cost * this in coin to invest
INVEST_MIN_UPTIME = 0.6       # only upgrade machines that actually run
INVEST_SELLOUT_DAYS = 3       # sold-out days in window to justify an upgrade

# Village tithe: daily % of everyone's coin pooled and redistributed equally.
# This is the MVP stand-in for wages -- without it, money drains one-way up
# the production chain and consumers go broke.
TITHE_RATE = 0.05

# Starting conditions
NPC_START_MONEY = 200
PLAYER_START_MONEY = 400
PLOT_SLOTS = 4
