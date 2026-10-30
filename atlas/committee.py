"""User-defined, evidenced committee reviews; advisory simulated actions only."""

from datetime import timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import json
from urllib.parse import urlsplit

from .core import timestamp

D = Decimal
DEFAULT_POLICY = dict(
    open_min=70,
    watch_min=55,
    strong_min=80,
    min_score_lenses_active=1,
    tie_band_upper=72,
    tie_downside_min=60,
    tie_downside_members=[],
    dissent_score_max=40,
    dissent_confidence_min=4,
    dissent_step=0.25,
    dissent_floor=0.5,
    dissent_block_at=3,
    max_multiplier=1,
    vote_max_age_days=30,
    timing_policy="all",
)


def _number(value, low, high, *, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float, str, D)):
        raise ValueError("Invalid committee numeric input")
    try:
        value = D(str(value))
    except InvalidOperation:
        raise ValueError("Invalid committee numeric input") from None
    if (
        not value.is_finite()
        or not low <= value <= high
        or integer
        and value != int(value)
    ):
        raise ValueError("Committee number outside allowed range")
    return value


def _text(value):
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 2000
        or any(ord(c) < 32 for c in value)
    ):
        raise ValueError("Invalid committee text")
    return value


def _hash(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, allow_nan=False, separators=(",", ":")
        ).encode()
    ).hexdigest()


def _evidence(records, *, cutoff, grade, since=None):
    """Validate metadata; availability/grade shortfalls require review."""
    if not isinstance(records, list):
        raise ValueError("Evidence must be an explicit array")
    eligible = False
    invalid = False
    for record in records:
        if not isinstance(record, dict) or record.get("grade") not in ("A", "B", "C"):
            raise ValueError("Evidence needs grade A, B or C")
        url = urlsplit(_text(record.get("source")))
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ValueError("Evidence needs a credential-free HTTPS source")
        observed, available = timestamp(record.get("observed_at")), timestamp(
            record.get("available_at")
        )
        if observed > available:
            raise ValueError("Evidence availability predates observation")
        if available > cutoff:
            invalid = True
        elif record["grade"] <= grade and (since is None or observed >= since):
            eligible = True
    return eligible and not invalid


def _configuration(config):
    if not isinstance(config, dict) or config.get("schema_version") != 1:
        raise ValueError("Committee schema_version must be 1")
    registry = config.get("members")
    if not isinstance(registry, list) or not 1 <= len(registry) <= 100:
        raise ValueError("Committee needs 1 to 100 user-defined members")
    members = {}
    for member in registry:
        if not isinstance(member, dict):
            raise ValueError("Invalid committee member")
        key = _text(member.get("id"))
        roles = member.get("roles")
        if (
            key in members
            or not isinstance(roles, list)
            or not roles
            or len(set(roles)) != len(roles)
            or not set(roles) <= {"score", "sizing", "timing", "veto"}
        ):
            raise ValueError("Invalid or duplicate committee roles")
        if type(member.get("required", True)) is not bool:
            raise ValueError("Member required must be boolean")
        weight = _number(member.get("weight", 0), 0, 100)
        if ("score" in roles) != (weight > 0):
            raise ValueError("Only score roles carry positive weights")
        if member.get("minimum_grade", "B") not in ("A", "B", "C"):
            raise ValueError("Invalid member evidence grade")
        if "sizing" in roles:
            _number(member.get("sizing_floor", 0.5), D(".5"), 1)
        elif "sizing_floor" in member:
            raise ValueError("Sizing bounds require the sizing role")
        members[key] = member
    if (
        sum((_number(m.get("weight", 0), 0, 100) for m in members.values()), D(0))
        != 100
    ):
        raise ValueError("Registered score weights must sum to 100")
    supplied = config.get("policy", {})
    if not isinstance(supplied, dict) or set(supplied) - set(DEFAULT_POLICY):
        raise ValueError("Unknown committee policy field")
    policy = dict(DEFAULT_POLICY, **supplied)
    for key in (
        "watch_min",
        "open_min",
        "strong_min",
        "tie_band_upper",
        "tie_downside_min",
        "dissent_score_max",
    ):
        policy[key] = _number(policy[key], 0, 100)
    if (
        not policy["watch_min"] <= policy["open_min"] <= policy["strong_min"]
        or policy["tie_band_upper"] < policy["open_min"]
    ):
        raise ValueError("Inconsistent committee thresholds")
    for key, low, high in (
        ("dissent_confidence_min", 1, 5),
        ("dissent_block_at", 1, 100),
        ("min_score_lenses_active", 1, len(members)),
        ("vote_max_age_days", 1, 365),
    ):
        policy[key] = int(_number(policy[key], low, high, integer=True))
    for key in ("dissent_step", "dissent_floor", "max_multiplier"):
        policy[key] = _number(policy[key], 0, 1)
    if policy["timing_policy"] not in ("all", "any"):
        raise ValueError("timing_policy must be all or any")
    downside = policy["tie_downside_members"]
    if (
        not isinstance(downside, list)
        or len(set(downside)) != len(downside)
        or any(
            key not in members or "score" not in members[key]["roles"]
            for key in downside
        )
    ):
        raise ValueError("Tie downside members must be registered score roles")
    rules = {}
    for rule in config.get("veto_rules", []):
        key = _text(rule.get("id"))
        holder = rule.get("holder")
        if (
            key in rules
            or holder not in members
            or "veto" not in members[holder]["roles"]
        ):
            raise ValueError("Veto rule needs a unique ID and authorized holder")
        _text(rule.get("scope"))
        _text(rule.get("trigger_condition"))
        _text(rule.get("cure_condition"))
        if rule.get("minimum_grade") not in ("A", "B"):
            raise ValueError("Veto rules require grade A or B")
        _number(rule.get("expiry_days"), 1, 365, integer=True)
        rules[key] = rule
    if any(
        "veto" in member["roles"]
        and not any(r["holder"] == key for r in rules.values())
        for key, member in members.items()
    ):
        raise ValueError("Every veto role needs an explicit narrow rule")
    return members, rules, policy


def evaluate(config, votes, *, as_of):
    """Return one reproducible advisory action, preserving unresolved veto history.

    Evidence, grades and cure satisfaction are operator attestations, not legal,
    financial or source verification. This function never authorizes live trading.
    """
    now = timestamp(as_of)
    members, rules, policy = _configuration(config)
    if not isinstance(votes, dict) or not isinstance(votes.get("members"), list):
        raise ValueError("votes.members must be an explicit array")
    if type(votes.get("previously_listed", False)) is not bool:
        raise ValueError("previously_listed must be boolean")
    supplied = {}
    for vote in votes["members"]:
        key = vote.get("id")
        if key not in members or key in supplied:
            raise ValueError("Unknown or duplicate committee vote")
        roles = members[key]["roles"]
        for field, role in (
            ("score", "score"),
            ("sizing_factor", "sizing"),
            ("timing", "timing"),
        ):
            if field in vote and role not in roles:
                raise ValueError("Vote exceeds member role authority")
        if "confidence" in vote:
            _number(vote["confidence"], 1, 5, integer=True)
        if "score" in vote:
            _number(vote["score"], 0, 100)
        if "sizing_factor" in vote:
            _number(
                vote["sizing_factor"],
                _number(members[key].get("sizing_floor", 0.5), D(".5"), 1),
                1,
            )
        if "timing" in vote and vote["timing"] not in ("pass", "wait"):
            raise ValueError("Timing votes must pass or wait")
        supplied[key] = vote
    blockers = []
    active, sizing, timing = {}, D(1), []
    for key, member in sorted(members.items()):
        vote = supplied.get(key)
        valid = False
        if vote is not None and all(
            field in vote
            for field in ("confidence", "observed_at", "available_at", "sources")
        ):
            observed, available = timestamp(vote["observed_at"]), timestamp(
                vote["available_at"]
            )
            if observed > available:
                raise ValueError("Vote availability predates observation")
            valid = observed <= available <= now and now - observed <= timedelta(
                days=policy["vote_max_age_days"]
            )
            valid = (
                _evidence(
                    vote["sources"],
                    cutoff=min(now, available),
                    grade=member.get("minimum_grade", "B"),
                )
                and valid
            )
            if "expires_at" in vote:
                expiry = timestamp(vote["expires_at"])
                if expiry <= observed:
                    raise ValueError("Vote expiry must follow observation")
                valid = valid and now < expiry
        if not valid and member.get("required", True):
            blockers.append("vote_review_required:" + key)
        roles = member["roles"]
        if "score" in roles:
            if valid and "score" in vote:
                active[key] = _number(vote["score"], 0, 100)
            elif member.get("required", True):
                blockers.append("score_missing:" + key)
        if "sizing" in roles:
            if valid and "sizing_factor" in vote:
                sizing *= _number(vote["sizing_factor"], D(".5"), 1)
            else:
                sizing *= _number(member.get("sizing_floor", 0.5), D(".5"), 1)
                if member.get("required", True):
                    blockers.append("sizing_review_required:" + key)
        if "timing" in roles:
            timing.append(bool(valid and vote.get("timing") == "pass"))
    if timing and not (
        all(timing) if policy["timing_policy"] == "all" else any(timing)
    ):
        blockers.append("timing_wait")
    score = sum(
        (
            value * _number(members[key]["weight"], 0, 100) / 100
            for key, value in active.items()
        ),
        D(0),
    )
    dissents = sum(
        value < policy["dissent_score_max"]
        and _number(supplied[key]["confidence"], 1, 5, integer=True)
        >= policy["dissent_confidence_min"]
        for key, value in active.items()
    )
    dissent_factor = max(policy["dissent_floor"], 1 - policy["dissent_step"] * dissents)
    cap = min(policy["max_multiplier"], sizing * dissent_factor)
    if cap == 0:
        blockers.append("zero_risk_capacity")
    if len(active) < policy["min_score_lenses_active"]:
        blockers.append("insufficient_score_coverage")
    if dissents >= policy["dissent_block_at"]:
        blockers.append("broad_dissent")
    downside = policy["tie_downside_members"]
    if (
        policy["open_min"] <= score < policy["tie_band_upper"]
        and downside
        and (
            any(key not in active for key in downside)
            or sum(active[key] for key in downside) / len(downside)
            < policy["tie_downside_min"]
        )
    ):
        blockers.append("tie_downside_not_satisfied")

    vetoes = votes.get("vetoes", [])
    if not isinstance(vetoes, list):
        raise ValueError("vetoes must be an explicit array")
    veto_records, seen = [], set()
    for veto in vetoes:
        key = _text(veto.get("id"))
        rule = rules.get(veto.get("rule_id"))
        if key in seen or rule is None or veto.get("member_id") != rule["holder"]:
            raise ValueError("Invalid veto holder or rule")
        seen.add(key)
        triggered, expiry = timestamp(veto.get("triggered_at")), timestamp(
            veto.get("expires_at")
        )
        if (
            not triggered
            < expiry
            <= triggered + timedelta(days=int(rule["expiry_days"]))
        ):
            raise ValueError("Veto expiry exceeds its registered rule")
        if (
            "trigger_condition_met" in veto
            and type(veto["trigger_condition_met"]) is not bool
        ):
            raise ValueError("Veto trigger_condition_met must be boolean")
        qualified = (
            veto.get("trigger_condition_met") is True
            and triggered <= now
            and _evidence(
                veto.get("evidence", []),
                cutoff=min(now, triggered),
                grade=rule["minimum_grade"],
            )
        )
        cured = False
        cure = veto.get("cure")
        if cure is not None:
            if (
                not isinstance(cure, dict)
                or type(cure.get("condition_met")) is not bool
            ):
                raise ValueError("Cure requires an explicit condition_met boolean")
            observed, available = timestamp(cure.get("observed_at")), timestamp(
                cure.get("available_at")
            )
            if observed > available or observed < triggered:
                raise ValueError("Cure must follow the veto trigger")
            cured = (
                cure["condition_met"]
                and available <= now
                and _evidence(
                    cure.get("evidence", []),
                    cutoff=min(now, available),
                    grade=rule["minimum_grade"],
                    since=triggered,
                )
            )
        status = (
            "CURED"
            if qualified and cured
            else (
                "REVIEW_REQUIRED"
                if not qualified
                else "EXPIRED_REVIEW_REQUIRED" if now >= expiry else "ACTIVE"
            )
        )
        veto_records.append(
            dict(
                id=key,
                rule_id=veto["rule_id"],
                scope=rule["scope"],
                status=status,
                cure_condition=rule["cure_condition"],
            )
        )
        if status != "CURED":
            blockers.append("veto:" + key + ":" + status.lower())
    external = votes.get("blockers", [])
    if not isinstance(external, list):
        raise ValueError("External blockers must be an array")
    blockers.extend("external:" + _text(value) for value in external)
    structural = votes.get("structural_reject")
    if structural is not None:
        blockers.append("structural:" + _text(structural))
    negative = "REDUCE_REMOVE" if votes.get("previously_listed", False) else "REJECT"
    if structural is not None or any(
        record["status"] == "ACTIVE" for record in veto_records
    ):
        action, label = negative, "negative"
    elif any(
        "review_required" in blocker
        or "missing" in blocker
        or blocker == "insufficient_score_coverage"
        for blocker in blockers
    ):
        action, label = "KEEP_WATCHLIST", "review_required"
    elif score < policy["watch_min"]:
        action, label = negative, "negative"
    elif score < policy["open_min"] or blockers:
        action, label = "KEEP_WATCHLIST", "split"
    else:
        action = "OPEN_PAPER_POSITION"
        label = "strong" if score >= policy["strong_min"] else "moderate"
    return dict(
        schema_version=1,
        as_of=now.isoformat(),
        action=action,
        action_state=action,
        score=float(score),
        committee_score=float(score),
        active_score_members=len(active),
        registered_score_weight=100,
        active_score_weight=float(
            sum((_number(members[key]["weight"], 0, 100) for key in active), D(0))
        ),
        strong_dissents=dissents,
        dissent_factor=float(dissent_factor),
        sizing_product=float(sizing),
        multiplier_cap=float(cap),
        risk_multiplier=float(cap) if action == "OPEN_PAPER_POSITION" else 0,
        label=label,
        blockers=sorted(set(blockers)),
        vetoes=veto_records,
        execution_enabled=False,
        config_sha256=_hash(config),
        votes_sha256=_hash(votes),
        limitations=[
            "Evidence grades and cure satisfaction remain operator attestations.",
            "Committee approval cannot override research, cash, risk or simulated-ledger gates.",
        ],
    )
