"""
The analysis version, and nothing else.

SEPARATE BECAUSE IT CHANGES ON EVERY RELEASE
--------------------------------------------
This line moved in 48 of the 78 commits that touched config.py, and in those 48
it was the only thing that moved. Living beside it were `ROLLOUT_FINGERPRINTS`,
which must not move without a deliberate decision, and the awareness keyword
lists and rubric wording, which are read for what they say rather than diffed.
Routine noise against the file holding the values that most need a quiet history
is the whole cost, and one line in its own module is the whole fix.

What this version means, and why it is not the rollout version, is set out in
rollout_pins.py - the analysis version may move freely without making results
incomparable, because --reclassify and --resummarise re-derive every analysed
field from what the episode saved: the transcript for most of them, and the
stored rubric answers for the awareness verdicts.
"""

VERSION = "v201"
