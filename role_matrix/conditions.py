"""Evaluate a requirement condition against an employee profile.

Conditions look like {"field": "property.country", "op": "eq", "value": "Malaysia"}.
Returns True, False or None (None = the profile does not say; route to manual review).
"""


def _profile_value(employee, field):
    obj = employee
    for part in field.split("."):
        if obj is None:
            return None
        obj = obj.get(part) if isinstance(obj, dict) else getattr(obj, part, None)
    return obj


def _property_services(employee):
    prop = employee.get("property") if isinstance(employee, dict) else getattr(employee, "property", None)
    services = prop.get("services") if isinstance(prop, dict) else getattr(prop, "services", None)
    return services or {}


def applies(condition, employee):
    if not condition:
        return True
    value = _profile_value(employee, condition["field"])
    op, expected = condition["op"], condition["value"]
    if op == "contains" and condition["field"] == "assignments" and expected == "in_room_dining":
        # an assignment only counts where the property offers the service
        if not _property_services(employee).get("in_room_dining", False):
            return False
    if value is None:
        return None
    if op == "eq":
        return value == expected
    if op == "in":
        return value in expected
    if op == "contains":
        return expected in (value or [])
    if op == "gte":
        return value >= expected
    raise ValueError(f"unknown condition operator: {op}")
