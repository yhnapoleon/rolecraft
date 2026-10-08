import numpy as np
import pytest

from career_lab.models.ensemble import blend


def test_endpoints_and_weights():
    a = np.array([[0.2, 0.3, 0.5]])
    b = np.array([[0.6, 0.2, 0.2]])
    np.testing.assert_array_equal(blend(a, b, 0), a)
    np.testing.assert_array_equal(blend(a, b, 1), b)
    with pytest.raises(ValueError):
        blend(a, b, 2)
