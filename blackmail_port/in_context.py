"""The blackmail port's primary contrast, with suspicion counted only where the act could see it.

An exploratory reading, not part of any analysis plan. The harness does not replay earlier
reasoning to most models (subversionbench/turn_context.py), so in a multi-turn episode suspicion
voiced in an earlier turn's reasoning is no longer in the model's context when it acts.
Suspicion is located by the awareness judge's evidence quotes. Three readings follow the plan's:

- turn level, the one to read: every turn up to and including the first message judged
  blackmail (or the last turn) is a unit, exposed if a quote was in view on that turn, and the
  event is the first blackmail on that turn (turn_context.turn_level_estimate);
- episode level at the first email sent, a window that does not depend on the outcome;
- episode level at the first blackmail, else the first email: biased toward a negative
  association by construction, since only a blackmailing episode is judged at its blackmail,
  and printed for the record.

An episode judged aware whose quotes are found nowhere is left out and counted. The judge quotes
a few passages, so suspicion repeated in view but quoted from elsewhere is missed, which biases
every reading toward no association. In a single-turn corpus every quote lies in the act's turn.
Prints counts and estimates, never transcript text.

    python3 -m blackmail_port.in_context --corpus eval_results_blackmail_r1
    python3 -m blackmail_port.in_context --corpus eval_results_blackmail1t_r3 --model kimi-k2.6
"""
import argparse

from blackmail_port import analyse as A
from blackmail_port import judge_common as J
from blackmail_port.judge_harm import sending_entries
from subversionbench.turn_context import (QUOTE_MIN, reasoning_replayed,
                                          resampled_odds_ratio_interval, seen_on_turn,
                                          turn_level_estimate, turn_units)



def evidence_quotes(record) -> list:
    evidence = ((record or {}).get("judge") or {}).get("model_awareness", {}).get("evidence") or []
    return [J.normalise(q)[:200] for q in evidence if isinstance(q, str) and len(q.strip()) >= QUOTE_MIN]


def quote_entries(transcript, quotes) -> list:
    """Indices of the reasoning, text and command entries holding a quote."""
    found = []
    for i, t in enumerate(transcript):
        kind = t.get("type")
        body = t.get("cmd") if kind == "tool_call" else t.get("content") if kind in ("text", "thinking") else None
        if body is not None and any(q in J.normalise(str(body)) for q in quotes):
            found.append(i)
    return found


def first_blackmail(transcript, episode, harm) -> tuple:
    """(index, turn) of the first sending command judged blackmail, or (None, None)."""
    for n, (i, turn, _cmd, _out) in enumerate(sending_entries(transcript)):
        unit = harm.get(f"{episode}#{n}")
        if unit and unit["judge"]["harmful_behavior"]["conclusion"].strip().lower() == "yes":
            return i, turn
    return None, None


def first_email_turn(transcript):
    turns = [turn for _i, turn, _cmd, _out in sending_entries(transcript)]
    return min(turns) if turns else max((t.get("turn") or 0 for t in transcript), default=0)


def with_context(r, e, harm, aware) -> dict:
    """The analysis row with where its suspicion lay and what the model could see when."""
    tr = e["transcript"]
    located = quote_entries(tr, evidence_quotes(aware.get(r["episode"]))) if r["aware"] == "safety" else []
    act_index, act_turn = first_blackmail(tr, r["episode"], harm)
    last = act_turn if act_turn is not None else max((t.get("turn") or 0 for t in tr), default=0)
    replayed = reasoning_replayed(e)
    first_email = first_email_turn(tr)
    return dict(r, located=located, replayed=replayed,
                units=turn_units(tr, located, last, act_index, act_turn is not None, replayed),
                at_first_email=seen_on_turn(tr, located, first_email, None, replayed),
                at_blackmail_or_email=seen_on_turn(tr, located, act_turn or first_email, act_index, replayed))


def threat_rows(corpus, plan) -> list:
    """The plan's analysed threat-arm rows, each with where its suspicion lies."""
    harm = A.verdicts(J.output_path("harm", corpus), "harmful_behavior")
    aware = A.verdicts(J.output_path("awareness", corpus), "model_awareness")
    screen = A.screen_patterns(J.bundle(corpus))
    rows = []
    for path, e in J.episodes(corpus):
        r = A.episode_row(path, e, harm, aware, screen)
        if (r["model"] not in plan or r["condition"] not in A.THREAT or r["harm_missing"]
                or r["aware"] not in ("safety", "unaware") or r["cut_off"]):
            continue
        rows.append(with_context(r, e, harm, aware))
    return rows


def episode_reading(label, rows, key):
    def exposed(r):
        return r["aware"] == "safety" and r[key]
    print(f"\n{label}")
    A.estimate("pooled", rows, exposed, lambda r: not exposed(r))
    A.estimate(f"{A.FOCAL} alone", [r for r in rows if r["model"] == A.FOCAL],
               exposed, lambda r: not exposed(r))


def turn_reading(rows):
    print("\nturn level, outcome-independent: odds ratio of a first blackmail on a turn")
    for label, sub in (("pooled", rows), (f"{A.FOCAL} alone", [r for r in rows if r["model"] == A.FOCAL])):
        mh = turn_level_estimate(sub, lambda r: (r["model"], r["condition"]))
        lo, hi, n = resampled_odds_ratio_interval(sub, lambda r: (r["model"], r["condition"]))
        units = [u for r in sub for u in r["units"]]
        ratio = "undefined" if mh.get("odds_ratio") is None else f"{mh['odds_ratio']:.3g}"
        interval = "" if not n else f" ({lo:.3g}, {hi:.3g}; {n} resamples)"
        print(f"{label:44} OR {ratio}{interval}  turns {len(units)}, exposed "
              f"{sum(e for _, e, _ in units)}, first blackmail {sum(v for _, _, v in units)}, in an "
              f"exposed turn {sum(e and v for _, e, v in units)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--corpus", default="eval_results_blackmail_r1")
    ap.add_argument("--model", action="append", default=None,
                    help="a model the plan covers (repeatable); default: the multi-turn port's six")
    a = ap.parse_args()
    corpus = a.corpus.rstrip("/")
    rows = threat_rows(corpus, set(a.model) if a.model else A.PLAN_MODELS)
    nowhere = [r for r in rows if r["aware"] == "safety" and not r["located"]]
    rows = [r for r in rows if r not in nowhere]
    print(f"{corpus}: {len(rows)} threat-arm episodes; {len(nowhere)} judged aware with no "
          "quote found, left out")
    print("\nthe plan's reading, on these episodes")
    A.estimate("pooled", rows, lambda r: r["aware"] == "safety", lambda r: r["aware"] == "unaware")
    A.estimate(f"{A.FOCAL} alone", [r for r in rows if r["model"] == A.FOCAL],
               lambda r: r["aware"] == "safety", lambda r: r["aware"] == "unaware")
    turn_reading(rows)
    episode_reading("in view at the first email (episode level)", rows, "at_first_email")
    episode_reading("in view at the first blackmail or email (biased toward a negative association)",
                    rows, "at_blackmail_or_email")


if __name__ == "__main__":
    main()
