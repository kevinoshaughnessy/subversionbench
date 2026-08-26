"""
The report as text on a terminal.

The third of the three renderings of one report - table, charts, JSON - and the
only one that always runs. It reads the document `report.py` returns and
computes nothing, so a figure printed here is the figure in the JSON.
"""



def _fmt_rate(member: dict) -> str:
    if member["rate"] is None:
        return f"{member['successes']}/{member['n']}"
    return f"{member['successes']}/{member['n']}={member['rate']:.1%}"


def _print_family(family: dict) -> None:
    print(f"\n{'=' * 78}")
    print(f"{family['family']}  ({family['n_members']} versions)")
    print(f"{'=' * 78}")
    if family["ordering_ambiguous"]:
        print("  !! version ordering depends on how a trailing-zero minor is "
              "read; this")
        print(f"     family is ordered by --version-style "
              f"{family['version_style']}. Try the other to compare.")
    print(f"  {'version':<10} {'model':<40} {'rate':>16} {'95% CI':>18}")
    for member in family["members"]:
        ci = (f"[{member['ci95'][0]:.1%}, {member['ci95'][1]:.1%}]"
              if member["ci95"] else "-")
        flag = " !" if member["underpowered"] else ""
        version = member["version"] or "-"
        if member["date"]:
            version += f"+{member['date']}"
        tags = f" ({','.join(member['tags'])})" if member["tags"] else ""
        print(f"  {version:<10} {member['model'] + tags:<40} "
              f"{_fmt_rate(member):>16} {ci:>18}{flag}")

    steps = family["steps_summary"]
    print(f"\n  steps: {steps['n_down']} down, {steps['n_up']} up, "
          f"{steps['n_flat']} flat")
    for step in family["steps"]:
        if step.get("difference") is None:
            print(f"    {step['from']} -> {step['to']}: {step.get('note')}")
            continue
        mark = {"down": "v", "up": "^", "flat": "="}[step["direction"]]
        print(f"    {mark} {step['from']} -> {step['to']}: "
              f"{step['difference']:+.1%}  p={step['p']:.4g}"
              f"{'  SEPARATED' if step['separated'] else ''}")

    trend = family["trend"]
    if trend.get("z") is None:
        print(f"\n  trend: not testable ({trend.get('note')})")
    else:
        extra = ""
        if trend.get("holm_p") is not None:
            extra = f"  holm={trend['holm_p']:.4g}  BH={trend['bh_p']:.4g}"
        print(f"\n  trend (Cochran-Armitage): z={trend['z']:+.3f} "
              f"p={trend['p']:.4g} {trend['direction']}{extra}")
    if family["first_vs_last"]:
        fl = family["first_vs_last"]
        print(f"  first vs last: {fl['difference']:+.1%}  "
              f"95% CI [{fl['difference_ci95'][0]:+.1%}, "
              f"{fl['difference_ci95'][1]:+.1%}]  p={fl['p']:.4g}")
    _print_release_fit(family.get("release_fit"))
    print(f"\n  => {family['verdict']}")


def _print_release_fit(fit: dict) -> None:
    """
    The slope the release charts draw as a dotted line.

    Printed so that the line on the chart is a second reading of a number in the
    report rather than the only place it exists. Labelled descriptive on every
    line it appears on: it has no p-value, and the trend test two lines above it
    does, so a reader skimming could easily take one for the other.
    """
    if not fit:
        return
    if fit.get("slope_per_month") is None:
        print(f"  release-date fit: none ({fit.get('note')})")
        return
    note = f"  - {fit['note']}" if fit.get("note") else ""
    print(f"  release-date fit (descriptive, no p-value): "
          f"{fit['slope_per_month'] * 100:+.1f} points/month across "
          f"{fit['span_days']} days and {fit['n_points']} "
          f"dated release(s){note}")


def _print_report(report: dict) -> None:
    print(f"\n{'#' * 78}")
    print(f"# Is the {report['metric_label']} falling within a model family?")
    print(f"# {report['output_dir']}   {report['n_families']} families   "
          f"version-style={report['version_style']}")
    print(f"{'#' * 78}")

    for family in report["families"]:
        _print_family(family)

    overall = report["across_all_families"]
    print(f"\n{'=' * 78}")
    print("ACROSS ALL FAMILIES")
    print(f"{'=' * 78}")
    print(f"  {overall['n_steps']} consecutive step(s): {overall['n_down']} "
          f"down, {overall['n_up']} up, {overall['n_flat']} flat")
    print(f"  families falling at every step: "
          f"{overall['n_families_monotone_falling']}/{report['n_families']}"
          f"   rising at every step: "
          f"{overall['n_families_monotone_rising']}/{report['n_families']}")
    sign = overall["sign_test"]
    if sign.get("p") is None:
        print(f"  sign test: {sign.get('note')}")
    else:
        print(f"  sign test on step direction: {sign['n_down']} down vs "
              f"{sign['n_up']} up, p={sign['p']:.4g}"
              f"{'  SEPARATED' if sign['separated'] else '  not separated'}")
    mult = overall["multiplicity"]
    if mult:
        print(f"  trend tests: {mult['n_tests']}, "
              f"{mult['uncorrected_rejections']} separated uncorrected, "
              f"{mult['holm_rejections']} survive Holm, "
              f"{mult['bh_rejections']} survive BH")

    dq = report["data_quality"]
    print(f"\n{'=' * 78}")
    print("DATA QUALITY")
    print(f"{'=' * 78}")
    print(f"  metric: {dq['metric']} - {dq['llm_dependency_note']}")
    print(f"  {dq['n_models_in_a_family']}/{dq['n_models_total']} model(s) sit "
          f"in a family with at least two members")
    if dq["models_without_a_family"]:
        print(f"  no family (only version collected): "
              f"{', '.join(dq['models_without_a_family'])}")
    if dq["models_below_informative_denominator"]:
        print(f"  ! below {dq['min_informative_denominator']} episodes: "
              f"{', '.join(dq['models_below_informative_denominator'])}")
    if dq["families_with_ambiguous_ordering"]:
        print(f"  ! ordering depends on --version-style: "
              f"{', '.join(dq['families_with_ambiguous_ordering'])}")
    if dq["unparsed_tokens"]:
        print(f"  ! tokens the parser did not recognise: "
              f"{', '.join(dq['unparsed_tokens'])}")
    _print_release_date_errors(dq)


def _print_release_date_errors(dq: dict) -> None:
    """
    Name every model with no recorded release date, loudly, and carry on.

    Louder than the warnings above it because it is the only line in the block
    that names a fix, and quieter than a failure because nothing above it
    depends on a release date: an undated model is missing from the release
    charts and present in every table, trend, interval and p-value. Stopping the
    analysis over a chart would be the wrong trade, so this returns nothing and
    changes no exit code.
    """
    missing = dq["models_without_release_date"]
    if not missing:
        return
    plotted = dq["plotted_models_without_release_date"]
    print(f"\n  !! ERROR: no release date recorded for {len(missing)} "
          f"model(s): {', '.join(missing)}")
    print(f"     Add them to RELEASE_DATES in model_releases.py. "
          f"{len(plotted)} of them sit in a family and are therefore MISSING "
          f"from the release-date charts;")
    print("     every figure above is unaffected, and so is every "
          "version-order chart.")
