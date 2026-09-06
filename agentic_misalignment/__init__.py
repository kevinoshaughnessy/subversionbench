"""
An external agentic-misalignment benchmark, and its correlation with the rates
measured here.

The data is a harmful-behaviour table from a separate agentic-misalignment
benchmark: counts of harmful trajectories per model, split three ways by whether
the model verbalised evaluation awareness, across three harm scenarios.

WHY IT IS NOT PLAIN SOURCE
--------------------------
The same reason the scenario and the situational-awareness leaderboard are not,
and the reasoning is written out in full in sad_oversight.py. Briefly: a
benchmark whose items sit in a public repository as plain text goes into the next
training crawl, and a model trained on it scores by recall. That destroys the
comparison this file exists to make.

So the table is encrypted at rest with the PUBLISHED passphrase, the same one
zip.sh uses. It offers no confidentiality; it is a crawler barrier.

    python3 -m agentic_misalignment --decode   # writes agentic_misalignment.json
    python3 -m agentic_misalignment --encode   # folds that file back in

agentic_misalignment.json is gitignored, so a decoded working copy cannot be
committed by accident. The model names and the harm-scenario names live inside
the bundle for the same reason the scores do - a mapping table in plaintext
would put half the benchmark back into the crawl.

THE CRYPTO IS IMPORTED, NOT COPIED
----------------------------------
`encrypt`/`decrypt` come from sad_oversight rather than being reimplemented
here. A second copy of a key-derivation routine is a second thing to keep in
step, and the two bundles are meant to stay readable by the same passphrase.

WHAT THIS COMPARISON CAN AND CANNOT SAY
---------------------------------------
Five models overlap. That is enough to report a rank correlation and nowhere
near enough to conclude anything from one, which is why every rho is returned
with its n and its leave-one-out range. A sixth model in the source table is
deliberately unmatched - see the bundle's `deliberately_unmatched` - because no
local model shares both its version and its size.

Two correlations are reported, and they are different claims:

  LEVEL - the external harmful-behaviour rate against the misalignment rate
  here. The weaker of the two, because the absolute rates are not commensurable:
  the scenarios differ, the harms differ, and one benchmark's "harmful" is not
  the other's "misaligned act". Only the ORDER of the models is comparable, and
  even that assumes the two constructs rank models similarly.

  AWARENESS SUPPRESSION - the gap between the unaware and aware harmful rates,
  on each side. This is the axis the two benchmarks genuinely share: both record
  whether the model verbalised that it might be under evaluation, and both can
  therefore ask whether awareness moves the harmful rate. A gap is a within-
  benchmark difference, so it is far less sensitive to the two benchmarks
  measuring different absolute things. Positive means awareness went with LESS
  harmful behaviour.

THE AWARENESS BUCKETS DO NOT LINE UP EXACTLY
--------------------------------------------
The external table splits awareness three ways; this benchmark records one
binary verdict. The two external aware buckets are pooled into one aware side
for the primary comparison, and the narrower variant is reported beside it so
the choice is visible rather than buried. Which pooling is right is not settled
by the data, so both are printed.

NEITHER SIDE IS AN EFFECT
-------------------------
The suppression gap conditions on something the model did - verbalising
awareness - which is a post-treatment variable on both benchmarks. A model that
recognises a test and then behaves differently may be behaving differently for
reasons that also caused it to recognise the test. The gap is a description of
two populations, and the report says so.

WHY THIS IS A PACKAGE AND NOT ONE FILE
--------------------------------------
Not size, though it was over the thousand-line limit. The reason is the same
seam trends/ was split on and states in its own __init__: a third of this
script was drawing, in a file that also computes Spearman coefficients, and
matplotlib is an optional extra whose absence must cost presentation and never
analysis. That boundary was written in the comments and had no file at it.

So the modules run analysis first, then presentation, and nothing points back:

  bundle      the encrypted table, and how its awareness buckets are read
  rates       both sides' rates, computed the same way so they are comparable
  pairing     which local model is which external row, and what is left over
  correlations  rho, its leave-one-out range, and every (scenario, act) pairing
  report      the whole comparison as a document. THE analysis.
  ------------ everything above is a number; everything below shows it --------
  console     the same figures as a table on a terminal
  charts      the four figures. Needs matplotlib; nothing above does
  cli         which mode was asked for, and what it writes

The command is `python3 -m agentic_misalignment`, for the reason report/ and
trends/ carry the same __main__.py: a package whose __init__ re-exports `main`
cannot also be run as a module without executing it twice.
"""


from . import (bundle, charts, cli, comparison, console, correlations,
               pairing, rates)
from .bundle import (ACTS, AWARE_POOLINGS, MEASURES, OVERALL, _BUNDLE_PATH,
                     _PLAIN_PATH, decrypt, encrypt, load_bundle)
from .rates import (_model_stats, _rate, external_rates,
                    external_rates_by_scenario, local_act_rates, local_rates)
from .pairing import (build_pairs, local_index, unmatched_models,
                      unmatched_rows)
from .correlations import (_series, best_scenario_act_pairing, correlate,
                        scenario_act_correlations, scenario_act_pairs)
from .comparison import build_report
from .console import print_report
from .charts import (CHART_DPI, _LABEL_OFFSETS, _place_labels, _slug, _wrap,
                     write_chart, write_scenario_act_chart,
                     write_scenario_charts)
from .cli import main

__all__ = [
    "ACTS", "AWARE_POOLINGS", "CHART_DPI", "MEASURES", "OVERALL",
    "bundle", "charts", "cli", "comparison", "console", "correlations",
    "pairing", "rates",
    "_BUNDLE_PATH", "_LABEL_OFFSETS", "_PLAIN_PATH", "_model_stats",
    "_place_labels", "_rate", "_series", "_slug", "_wrap",
    "best_scenario_act_pairing", "build_pairs", "build_report", "correlate",
    "decrypt", "encrypt", "external_rates", "external_rates_by_scenario",
    "load_bundle", "local_act_rates", "local_index", "local_rates", "main",
    "print_report", "scenario_act_correlations", "scenario_act_pairs",
    "unmatched_models", "unmatched_rows", "write_chart",
    "write_scenario_act_chart", "write_scenario_charts",
]
