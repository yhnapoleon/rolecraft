"""Compare against the fully remapped prefix; never drop business/version fields."""
from career_lab.contracts.v2 import SnapshotExport, digest


def prefix_value(snapshot):
    value = snapshot.model_dump(mode="json", exclude={"id", "snapshot_hash"})
    # Storage row ordering is not a business property; event ordering is.
    value["objects"] = sorted(value["objects"], key=lambda o: (
        o["ref"]["kind"], o["ref"]["object_id"], o["ref"]["version"]))
    return value


def field_differences(expected, actual, path=""):
    if type(expected) is not type(actual):
        return [{"path": path or "/", "expected": expected, "actual": actual}]
    result = []
    if isinstance(expected, dict):
        for key in sorted(expected.keys() | actual.keys()):
            at = path + "/" + key.replace("~", "~0").replace("/", "~1")
            if key not in expected or key not in actual:
                result.append({"path": at, "expected_present": key in expected,
                               "actual_present": key in actual})
            else:
                result.extend(field_differences(expected[key], actual[key], at))
    elif isinstance(expected, list):
        if len(expected) != len(actual):
            result.append({"path": path + "/length", "expected": len(expected), "actual": len(actual)})
        for i, (a, b) in enumerate(zip(expected, actual)):
            result.extend(field_differences(a, b, path + "/" + str(i)))
    elif expected != actual:
        result.append({"path": path or "/", "expected": expected, "actual": actual})
    return result


def compare_prefix(expected: SnapshotExport, actual: SnapshotExport):
    expected = SnapshotExport.model_validate_json(expected.model_dump_json())
    actual = SnapshotExport.model_validate_json(actual.model_dump_json())
    left, right = prefix_value(expected), prefix_value(actual)
    differences = field_differences(left, right)
    return {"equal": not differences, "expected_digest": digest(left),
            "actual_digest": digest(right), "differences": differences,
            "ignored_fields": ["snapshot.id", "snapshot.snapshot_hash"],
            "normalization": "expected prefix already maps all identities into the child namespace"}
