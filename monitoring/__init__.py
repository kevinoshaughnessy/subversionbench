"""
The transcript-monitoring scenario: the model under evaluation is a MONITOR.

It is shown transcripts other scenarios already collected and asked how
suspicious the agent's conduct was, and at which step it first went wrong. The
ground truth is the detector's verdict on each episode and the step it located
the act at, so a monitor is scored on what it caught, how early, and at what
false-positive rate.

Each collected scenario is an ARM of this one (arms.py): a new scenario's corpus
becomes a new arm by adding it there, and nothing else changes.

    sample   draw the episodes: equal numbers with and without a misaligned act
    run      put them to one monitor, in each view and at each cut
    report   score every monitor that has been run

The monitor's instructions are held base64-encoded in monitor.b64, as the
detector text is, because how a monitor is told to look is the protocol a model
trained on it would learn. `python3 -m monitoring.bundle --list`
reads it.
"""
