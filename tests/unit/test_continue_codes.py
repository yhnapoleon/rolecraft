"""What a person may type as a continue code. The browser applies the same examples."""

import re

import pytest

from career_lab.api.continue_codes import grouped, new_code, normalize

CODE = "7K3QM9XRPD2WTHC6NJAF"


@pytest.mark.parametrize(
    "typed",
    [
        "7K3Q-M9XR-PD2W-THC6-NJAF",
        "7k3q m9xr pd2w thc6 njaf",
        "  7K3Q–M9XR—PD2W−THC6‐NJAF  ",
        "７Ｋ３Ｑ－Ｍ９ＸＲ－PD2W　THC6NJAF",
    ],
)
def test_case_spaces_dashes_and_full_width_forms_are_the_same_code(typed: str) -> None:
    assert normalize(typed) == CODE


def test_o_reads_as_zero_and_i_or_l_as_one() -> None:
    assert normalize("OoIl-ABCD-EFGH-JKMN-PQRS") == "0011ABCDEFGHJKMNPQRS"


@pytest.mark.parametrize(
    "typed",
    [
        "",
        "7K3Q-M9XR-PD2W-THC6-NJA",
        "7K3Q-M9XR-PD2W-THC6-NJAFX",
        "7K3Q-M9XR-PD2W-THC6-NJAU",
        "7K3Q_M9XR_PD2W_THC6_NJAF",
        "继续码7K3QM9XRPD2WTHC6NJAF",
    ],
)
def test_anything_else_is_not_a_code(typed: str) -> None:
    assert normalize(typed) is None


def test_new_codes_are_100_random_bits_in_five_groups() -> None:
    codes = {new_code() for _ in range(1000)}
    assert len(codes) == 1000
    for code in codes:
        assert re.fullmatch(r"[0-9A-HJKMNP-TV-Z]{20}", code)
        assert re.fullmatch(r"([0-9A-HJKMNP-TV-Z]{4}-){4}[0-9A-HJKMNP-TV-Z]{4}", grouped(code))
        assert normalize(grouped(code)) == code
