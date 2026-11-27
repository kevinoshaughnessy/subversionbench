"""
Read a blackmail-port corpus after collection: judge what each episode sent and
what it said, then apply the analysis plan.

The ports (`subversionbench/scenarios/blackmail.b64`, and `blackmail1t.b64` in a
single turn) declare no act artefacts, so the harness records no act. The act is
a sent email, read here:

    python3 -m blackmail_port.judge_harm        every sent email, against Agentic
                                                Misalignment's blackmail criteria
    python3 -m blackmail_port.judge_awareness   Agentic Misalignment's own awareness
                                                reading, then --timing
    python3 -m blackmail_port.analyse           the plan's estimates and checks
    python3 -m blackmail_port.in_context        exploratory: suspicion counted only
                                                where the act could see it

The judges reach GPT-6.1 Terra through the routing of the public
decomposing-eval-awareness repository, and take its judge prompt and blackmail
criteria from there, so the instrument is the one Agentic Misalignment's regrade
used. See docs/operations.md, "Reading the blackmail port".
"""
