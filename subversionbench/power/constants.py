"""The numbers every module here shares, and the reason each is what it
is.

Their own module rather than the package __init__, so a submodule can
import them without importing the package that imports the submodule.
"""


Z_95 = 1.96
DEFAULT_ALPHA = 0.05
DEFAULT_TARGET_POWER = 0.80

# Above this per-arm n, the exact enumeration is O(n^3) and too slow to run
# by default, so two_arm_power() falls back to a normal approximation.
EXACT_MAX_N = 250

# Denominator below which a rate should be read as a raw count instead. A
# conditional metric like the confession rate has the misaligned-episode
# count as its denominator, not n, so a 100-run batch with a 10%
# misalignment rate reports it over 10 runs - an interval ~50 points wide.
MIN_INFORMATIVE_DENOMINATOR = 20
