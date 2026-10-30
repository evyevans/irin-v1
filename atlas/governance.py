"""Pure opt-in readiness, review deadlines and notification bookkeeping.

Records are operator attestations. Nothing here sends notices or enables trading.
"""

from copy import deepcopy
import json

from .core import timestamp


def _text(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Nonempty identifier/text required")
    return value


def _config(config):
    if not isinstance(config, dict) or set(config) != {"required_checks"}:
        raise ValueError("Governance config requires required_checks only")
    names = config["required_checks"]
    if not isinstance(names, list) or not names:
        raise ValueError("At least one required readiness check is required")
    for name in names:
        _text(name)
    if len(set(names)) != len(names):
        raise ValueError("Duplicate readiness check name")


def _copy(state):
    out = deepcopy(state)
    g = out.get("governance")
    if not isinstance(g, dict):
        raise ValueError("Configure governance before recording operational state")
    _config(g.get("config"))
    if any(not isinstance(g.get(key), dict) for key in ("checks", "reviews", "outbox")):
        raise ValueError("Malformed governance records")
    if not isinstance(g.get("history"), list):
        raise ValueError("Malformed governance history")
    return out, g


def configure(state, config):
    """Install/replace check requirements while retaining all operational records."""
    _config(config)
    if "governance" in state:
        out, g = _copy(state)
    else:
        out = deepcopy(state)
        g = dict(config=deepcopy(config), checks={}, reviews={}, outbox={}, history=[])
        out["governance"] = g
    if g["config"] != config or not g["history"]:
        g["history"].append(dict(kind="configure", config=deepcopy(config)))
    g["config"] = deepcopy(config)
    return out


def record_check(state, name, passed, *, observed_at, expires_at):
    """Record a boolean health observation; later observations supersede earlier ones."""
    out, g = _copy(state)
    _text(name)
    if name not in g["config"]["required_checks"] or type(passed) is not bool:
        raise ValueError("Configured check name and explicit boolean required")
    if timestamp(expires_at) <= timestamp(observed_at):
        raise ValueError("Health expiry must follow observation")
    record = dict(passed=passed, observed_at=observed_at, expires_at=expires_at)
    old = g["checks"].get(name)
    if old == record:
        return out
    if old and timestamp(observed_at) <= timestamp(old["observed_at"]):
        raise ValueError("Check observations cannot conflict or move backward")
    g["checks"][name] = record
    g["history"].append(dict(kind="check", name=name, **record))
    return out


def add_review(state, task_id, *, due_at, detail=""):
    """Add immutable review terms; an ID cannot be reused for different work."""
    out, g = _copy(state)
    _text(task_id)
    timestamp(due_at)
    if not isinstance(detail, str):
        raise ValueError("Review detail must be text")
    terms = dict(due_at=due_at, detail=detail)
    old = g["reviews"].get(task_id)
    if old:
        if old["terms"] != terms:
            raise ValueError("Review ID conflict")
        return out
    g["reviews"][task_id] = dict(terms=terms, resolved_at=None)
    g["history"].append(dict(kind="review_added", id=task_id, **terms))
    return out


def resolve_review(state, task_id, *, resolved_at):
    out, g = _copy(state)
    timestamp(resolved_at)
    if task_id not in g["reviews"]:
        raise ValueError("Unknown review ID")
    old = g["reviews"][task_id]["resolved_at"]
    if old is not None:
        if old != resolved_at:
            raise ValueError("Review resolution is immutable")
        return out
    g["reviews"][task_id]["resolved_at"] = resolved_at
    g["history"].append(dict(kind="review_resolved", id=task_id, at=resolved_at))
    return out


def queue_notice(state, task_id, *, deadline_at, payload=None):
    """Persist an outbox request only; no delivery channel is invoked."""
    out, g = _copy(state)
    _text(task_id)
    timestamp(deadline_at)
    if payload is not None and not isinstance(payload, dict):
        raise ValueError("Notice payload must be an object")
    json.dumps(payload, allow_nan=False)
    terms = dict(deadline_at=deadline_at, payload=deepcopy(payload or {}))
    old = g["outbox"].get(task_id)
    if old:
        if old["terms"] != terms:
            raise ValueError("Notice ID conflict")
        return out
    g["outbox"][task_id] = dict(terms=terms, status="queued", at=None, evidence=None)
    g["history"].append(dict(kind="notice_queued", id=task_id, **deepcopy(terms)))
    return out


def acknowledge_notice(state, task_id, *, status, at, evidence=None):
    """Record reserved/sent/failed status supplied by an external operator/adapter."""
    out, g = _copy(state)
    now = timestamp(at)
    if task_id not in g["outbox"]:
        raise ValueError("Unknown notice ID")
    record = g["outbox"][task_id]
    update = dict(status=status, at=at, evidence=evidence)
    if all(record.get(key) == value for key, value in update.items()):
        return out
    transitions = {
        "queued": {"reserved", "failed"},
        "reserved": {"sent", "failed"},
        "failed": {"reserved"},
        "sent": set(),
    }
    if status not in transitions.get(record["status"], set()):
        raise ValueError("Invalid outbox transition")
    if record["at"] is not None and now <= timestamp(record["at"]):
        raise ValueError("Notice transitions must move forward in time")
    if evidence is not None:
        _text(evidence)
    if status == "sent":
        _text(evidence)
    record.update(update)
    g["history"].append(dict(kind="notice_status", id=task_id, **update))
    return out


def assess(state, *, as_of):
    """Return READY/HOLD without modifying enablement, halt switches or input state.

    Absent governance preserves legacy behavior. Explicit malformed governance
    fails closed, as do absent/failed/stale checks and overdue operational work.
    """
    now = timestamp(as_of)
    configured = "governance" in state
    reasons, checks, reviews, notices = [], {}, [], []
    if configured:
        try:
            _, g = _copy(state)
            for name in g["config"]["required_checks"]:
                record = g["checks"].get(name)
                status = "missing"
                if record is not None:
                    if type(record["passed"]) is not bool:
                        raise ValueError("Invalid readiness boolean")
                    observed, expires = timestamp(record["observed_at"]), timestamp(
                        record["expires_at"]
                    )
                    if expires <= observed:
                        raise ValueError("Invalid health interval")
                    status = (
                        "future"
                        if observed > now
                        else (
                            "stale"
                            if expires <= now
                            else "passed" if record["passed"] else "failed"
                        )
                    )
                checks[name] = status
                if status != "passed":
                    reasons.append("check:" + name + ":" + status)
            for key, record in g["reviews"].items():
                _text(key)
                if not isinstance(record["terms"]["detail"], str):
                    raise ValueError("Invalid review detail")
                due = timestamp(record["terms"]["due_at"])
                resolved = record["resolved_at"]
                resolved_time = timestamp(resolved) if resolved is not None else None
                if due <= now and (resolved_time is None or resolved_time > now):
                    reviews.append(key)
                    reasons.append("review_overdue:" + key)
            for key, record in g["outbox"].items():
                _text(key)
                deadline = timestamp(record["terms"]["deadline_at"])
                if not isinstance(record["terms"]["payload"], dict):
                    raise ValueError("Invalid notice payload")
                json.dumps(record["terms"]["payload"], allow_nan=False)
                status = record["status"]
                if status not in ("queued", "reserved", "sent", "failed"):
                    raise ValueError("Invalid notice status")
                at = timestamp(record["at"]) if record["at"] is not None else None
                if record["evidence"] is not None:
                    _text(record["evidence"])
                if status == "queued" and (
                    at is not None or record["evidence"] is not None
                ):
                    raise ValueError("Invalid initial notice state")
                if status != "queued" and (at is None or at > now):
                    reasons.append("notice_unverified:" + key)
                if status == "sent" and not record.get("evidence"):
                    reasons.append("notice_unverified:" + key)
                if status == "failed":
                    reasons.append("notice_failed:" + key)
                if deadline <= now and (status != "sent" or at is None or at > now):
                    notices.append(key)
                    reasons.append("notice_overdue:" + key)
        except (ValueError, TypeError, KeyError, AttributeError):
            reasons.append("governance_invalid")
    ready = not reasons
    return dict(
        configured=configured,
        ready=ready,
        mode="READY" if ready else "HOLD",
        as_of=as_of,
        reasons=reasons,
        checks=checks,
        overdue_reviews=reviews,
        overdue_notices=notices,
        entries_allowed=bool(
            ready and state.get("enabled") and not state.get("halted")
        ),
    )
