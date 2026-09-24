"""Which local model is which external row, and what is left over.

Built from the bundle's alias list rather than by string similarity: the
two naming schemes have no derivable relation, and guessing gets it wrong
in ways that flip a correlation this small.
"""

from .rates import external_rates


def local_index(bundle: dict) -> dict:
    """
    Local model ID -> the external row it corresponds to.

    From the bundle's alias list, never by string similarity. The two naming
    schemes have no derivable relation and the failure is silent: a version or a
    size that differs by one token is a different model, and with five pairs one
    wrong pairing moves every rho reported here. sad_oversight.local_index
    records three real cases, all substring relationships.
    """
    index = {}
    for alias in bundle["aliases"]:
        for local in alias["local_models"]:
            index[local] = alias["external_model"]
    return index


def unmatched_rows(bundle: dict) -> list:
    """
    External models with no local counterpart, and whether that was a decision.

    The guard that makes a hand-maintained mapping safe, the same role
    model_releases.missing_dates plays: a row is never dropped silently. A row
    listed in `deliberately_unmatched` is reported as a decision; anything else
    is reported as a gap.
    """
    aliased = {a["external_model"] for a in bundle["aliases"]}
    decided = {d["external_model"]: d["reason"]
               for d in bundle.get("deliberately_unmatched") or []}
    out = []
    for model in dict.fromkeys(r["model"] for r in bundle["rows"]):
        if model in aliased:
            continue
        out.append({"external_model": model,
                    "decided": model in decided,
                    "reason": decided.get(model)})
    return out


def unmatched_models(bundle: dict, models: list) -> list:
    """Local models with no external row, in the order given."""
    index = local_index(bundle)
    return [m for m in models if m not in index]


def build_pairs(bundle: dict, local: dict, pooling: str = "any_aware") -> list:
    """One row per (external model, local model) the alias list joins."""
    external = external_rates(bundle, pooling)
    pairs = []
    for local_model, external_model in sorted(local_index(bundle).items()):
        if local_model not in local or external_model not in external:
            continue
        pairs.append({
            "local_model": local_model,
            "external_model": external_model,
            "external": external[external_model],
            "local": local[local_model],
        })
    return pairs
