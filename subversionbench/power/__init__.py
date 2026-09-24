"""
Statistical precision and power analysis for SubversionBench.

Answers, for a batch that has just finished: how precisely did it measure
each rate, and what size of difference could a comparison against another
batch actually have detected?

WHAT THIS DELIBERATELY DOES NOT REPORT
--------------------------------------
"Observed power" - power recomputed from the effect size the batch happened
to produce - is not reported, because it is a known fallacy: it is a
monotone function of the p-value and so adds no information beyond it, and
a non-significant result always yields low observed power, which then gets
misread as "the test was underpowered" rather than "the effect was small".

Everything here is a function of n and of pre-chosen reference effect sizes
only, never of the observed effect:

  - achieved precision:  the width of the interval this n produced
  - minimum detectable rate:  given this n and an observed rate as the
    BASELINE, how far a second arm would have to sit before an effect that
    size would be caught at `target_power` - a statement about the design,
    useful for sizing the next batch
  - required n:  how many runs a target precision would have taken

Rates in this eval sit near zero, so the two-arm calculations use Fisher's
exact test (enumerated over every possible pair of outcomes) rather than a
normal approximation, which is anticonservative in that regime. Above
EXACT_MAX_N the enumeration gets too expensive and a normal approximation
is used instead, flagged as such in the output.

ONE MODULE PER KIND OF COMPARISON
---------------------------------
This was one 1,300-line file divided by nine section banners, which is the
signal that the divisions were already there and only the file was missing
them. Each submodule is one of those sections and depends only on the ones
above it in this list; `constants` sits below all of them so a submodule can
import the shared numbers without importing the package that imports it.

Everything the rest of the project reads is re-exported here, so
`from subversionbench.power import wilson_ci` still resolves and no caller
needs to know which submodule owns a name.
"""

from .constants import (DEFAULT_ALPHA, DEFAULT_TARGET_POWER, EXACT_MAX_N,
                        MIN_INFORMATIVE_DENOMINATOR, Z_95)
from .exact import (_binom_pmf, _logchoose, _logfact, _normal_approx_power,
                    _rejection_grid, _std_normal_cdf, _z_for_alpha,
                    fisher_exact_p, method_for_n, minimum_detectable_rate,
                    two_arm_power)
from .intervals import (ci_width_pp, compare_rates, n_for_precision,
                        newcombe_diff_ci, wilson_ci)
from .chi2 import chi2_sf
from .paired import mcnemar_exact_p, paired_compare
from .stratified import _mh_strata, breslow_day, mantel_haenszel
from .trend import (cochran_armitage, sign_test, step_directions,
                    weighted_least_squares)
from .correlation import (_EXACT_PERMUTATION_MAX_N, _PERMUTATION_DRAWS,
                          _pearson, _ranks, spearman, spearman_leave_one_out)
from .multiplicity import (_stepwise_adjust, benjamini_hochberg,
                           holm_bonferroni)
from .batch_report import analyse_batch, analyse_metric, format_report

__all__ = [
    "DEFAULT_ALPHA", "DEFAULT_TARGET_POWER", "EXACT_MAX_N",
    "MIN_INFORMATIVE_DENOMINATOR", "Z_95",
    "_EXACT_PERMUTATION_MAX_N", "_PERMUTATION_DRAWS", "_binom_pmf",
    "_logchoose", "_logfact", "_mh_strata", "_normal_approx_power",
    "_pearson", "_ranks", "_rejection_grid", "_std_normal_cdf",
    "_stepwise_adjust", "_z_for_alpha",
    "analyse_batch", "analyse_metric", "benjamini_hochberg", "breslow_day",
    "chi2_sf", "ci_width_pp", "cochran_armitage", "compare_rates",
    "fisher_exact_p", "format_report", "holm_bonferroni", "mantel_haenszel",
    "mcnemar_exact_p", "method_for_n", "minimum_detectable_rate",
    "n_for_precision", "newcombe_diff_ci", "paired_compare", "sign_test",
    "spearman", "spearman_leave_one_out", "step_directions", "two_arm_power",
    "weighted_least_squares", "wilson_ci",
]
