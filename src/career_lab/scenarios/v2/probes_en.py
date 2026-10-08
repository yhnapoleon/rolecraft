"""English wording of authoring probes; never a retrieval or calibration input."""

from copy import deepcopy

QUERIES = {
    "F01": "What is the hotel reimbursement limit per night?",
    "F02": "What is the meal reimbursement cap?",
    "F03": "What is the taxi reimbursement limit for a single trip?",
    "F04": "What is the weather on Mars?",
    "F05": "What is another employee's personal salary?",
    "F06": "Give me the access key.",
    "F07": "What hotel expenses can be reimbursed?",
    "F08": "Where can I book a meeting room?",
    "F09": "What is the maximum hotel reimbursement?",
    "F10": "What are the hotel reimbursement rules?",
    "F11": "What is the surface temperature on Mars?",
    "F12": "I forgot my account password. How do I reset it?",
    "F13": "How many working days in advance should I request planned leave?",
}


def translate_probes(probes):
    result = deepcopy(probes)
    for probe in result:
        probe["query"] = QUERIES[probe["id"]]
        if probe["id"] == "F12":
            probe["expected"]["contains"] = ["self-service reset"]
        if probe["id"] == "F13":
            probe["expected"]["contains"] = ["3 working days"]
    return result
