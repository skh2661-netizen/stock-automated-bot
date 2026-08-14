# contract_utils.py
import math
import numbers

def _is_finite_real(value):
    """bool 우회를 완벽히 배제한 순수 실수(Finite Real) 검증"""
    return isinstance(value, numbers.Real) and type(value) is not bool and math.isfinite(float(value))

def _is_strict_int(value):
    """bool 우회를 완벽히 배제한 순수 정수 검증"""
    return type(value) is int
