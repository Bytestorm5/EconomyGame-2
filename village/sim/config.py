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

# NPC daily price adjustment
PRICE_UP_FACTOR = 1.15      # sold out -> raise
PRICE_DOWN_FACTOR = 0.9     # stock piling up -> lower
PRICE_MIN = 1
STOCKPILE_THRESHOLD = 10    # "piling up" if unsold stock exceeds this

# Village tithe: daily % of everyone's coin pooled and redistributed equally.
# This is the MVP stand-in for wages -- without it, money drains one-way up
# the production chain and consumers go broke.
TITHE_RATE = 0.05

# Starting conditions
NPC_START_MONEY = 200
PLAYER_START_MONEY = 400
PLOT_SLOTS = 4
