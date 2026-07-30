import math

import numpy as np


def to_json_value(value):
    """수집 단계의 값을 JSONB에 저장할 수 있는 기본형으로 바꿉니다."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return None if np.isnan(value) else float(value)
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [to_json_value(item) for item in value]
    return str(value)
