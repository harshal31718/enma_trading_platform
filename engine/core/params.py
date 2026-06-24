"""Typed self-validating strategy parameter classes (A-005).

Mirrors freqtrade's IntParameter / DecimalParameter / CategoricalParameter
pattern: bounds are enforced at construction, type is preserved, and each
parameter is a single declaration usable by the engine, UI, and optimizer.

Usage::

    from engine.core.params import IntParameter, FloatParameter

    class MyStrategy(BaseStrategy):
        PARAMS = {
            "fast_period": IntParameter(2, 50, default=12, label="Fast EMA Period"),
            "threshold": FloatParameter(0.1, 5.0, default=1.5, label="ATR Mult"),
        }
"""

from abc import ABC, abstractmethod
from typing import Any, Sequence


class BaseParameter(ABC):
    """Abstract base for all typed strategy parameters."""

    param_type: str = ""

    def __init__(
        self,
        default: Any = None,
        *,
        label: str = "",
        description: str = "",
    ):
        if label:
            self.label = label
        else:
            self.label = ""
        self.description = description
        self.default = default
        self.value = default

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.value!r})"

    @abstractmethod
    def to_dict(self) -> dict:
        ...

    @abstractmethod
    def coerce(self, raw: Any) -> Any:
        """Cast raw input to the parameter's native type, or raise TypeError."""

    @abstractmethod
    def validate(self, value: Any) -> None:
        """Raise ValueError if value is out of range or invalid."""


class IntParameter(BaseParameter):
    """Integer parameter with inclusive [min, max] bounds."""

    param_type = "int"

    def __init__(
        self,
        min_val: int,
        max_val: int,
        default: int,
        *,
        label: str = "",
        description: str = "",
    ):
        if not isinstance(default, int):
            raise TypeError(
                f"IntParameter default must be int, got {type(default).__name__}"
            )
        if min_val > max_val:
            raise ValueError(
                f"IntParameter min ({min_val}) > max ({max_val})"
            )
        if default < min_val or default > max_val:
            raise ValueError(
                f"IntParameter default {default} out of range [{min_val}, {max_val}]"
            )
        self.min = min_val
        self.max = max_val
        super().__init__(default, label=label, description=description)

    def coerce(self, raw: Any) -> int:
        return int(raw)

    def validate(self, value: int) -> None:
        if value < self.min or value > self.max:
            raise ValueError(
                f"Value {value} out of range [{self.min}, {self.max}]"
            )

    def to_dict(self) -> dict:
        return {
            "type": "int",
            "default": self.default,
            "min": self.min,
            "max": self.max,
            "label": self.label,
            "description": self.description,
        }


class FloatParameter(BaseParameter):
    """Float parameter with inclusive [min, max] bounds."""

    param_type = "float"

    def __init__(
        self,
        min_val: float,
        max_val: float,
        default: float,
        *,
        label: str = "",
        description: str = "",
    ):
        if not isinstance(default, (int, float)):
            raise TypeError(
                f"FloatParameter default must be numeric, got {type(default).__name__}"
            )
        if min_val > max_val:
            raise ValueError(
                f"FloatParameter min ({min_val}) > max ({max_val})"
            )
        if default < min_val or default > max_val:
            raise ValueError(
                f"FloatParameter default {default} out of range [{min_val}, {max_val}]"
            )
        self.min = float(min_val)
        self.max = float(max_val)
        super().__init__(float(default), label=label, description=description)

    def coerce(self, raw: Any) -> float:
        return float(raw)

    def validate(self, value: float) -> None:
        if value < self.min or value > self.max:
            raise ValueError(
                f"Value {value} out of range [{self.min}, {self.max}]"
            )

    def to_dict(self) -> dict:
        return {
            "type": "float",
            "default": self.default,
            "min": self.min,
            "max": self.max,
            "label": self.label,
            "description": self.description,
        }


class DecimalParameter(FloatParameter):
    """Float parameter rounded to a fixed number of decimal places."""

    param_type = "decimal"

    def __init__(
        self,
        min_val: float,
        max_val: float,
        default: float,
        decimals: int = 3,
        *,
        label: str = "",
        description: str = "",
    ):
        self.decimals = decimals
        rounded = round(float(default), decimals)
        super().__init__(min_val, max_val, rounded, label=label, description=description)
        self.value = self.default
        self.decimals = decimals

    def coerce(self, raw: Any) -> float:
        return round(float(raw), self.decimals)

    def validate(self, value: float) -> None:
        value = round(value, self.decimals)
        super().validate(value)

    def to_dict(self) -> dict:
        base = super().to_dict()
        base["type"] = "decimal"
        base["decimals"] = self.decimals
        return base


class CategoricalParameter(BaseParameter):
    """Parameter constrained to a fixed set of values."""

    param_type = "categorical"

    def __init__(
        self,
        categories: Sequence[Any],
        default: Any = None,
        *,
        label: str = "",
        description: str = "",
    ):
        if len(categories) < 2:
            raise ValueError(
                "CategoricalParameter requires at least 2 categories"
            )
        self.categories = list(categories)
        if default is None:
            default = self.categories[0]
        if default not in self.categories:
            raise ValueError(
                f"CategoricalParameter default {default!r} not in {self.categories}"
            )
        self.min = None
        self.max = None
        super().__init__(default, label=label, description=description)

    def coerce(self, raw: Any) -> Any:
        return raw

    def validate(self, value: Any) -> None:
        if value not in self.categories:
            raise ValueError(
                f"Value {value!r} not in allowed categories: {self.categories}"
            )

    def to_dict(self) -> dict:
        return {
            "type": "categorical",
            "default": self.default,
            "categories": self.categories,
            "label": self.label,
            "description": self.description,
        }


class BooleanParameter(CategoricalParameter):
    """Convenience parameter for True/False flags."""

    param_type = "boolean"

    def __init__(
        self,
        default: bool = True,
        *,
        label: str = "",
        description: str = "",
    ):
        super().__init__(
            [True, False], default=default, label=label, description=description
        )

    def to_dict(self) -> dict:
        return {
            "type": "boolean",
            "default": self.default,
            "label": self.label,
            "description": self.description,
        }


def _is_typed_param(obj: Any) -> bool:
    """Return True if *obj* is a typed-parameter instance (A-005),
    False if it is a legacy dict-style PARAMS entry."""
    return isinstance(obj, BaseParameter)


def param_min(obj: Any) -> Any:
    """Return the min bound from either a typed param or a dict entry."""
    return obj.min if _is_typed_param(obj) else obj["min"]


def param_max(obj: Any) -> Any:
    """Return the max bound from either a typed param or a dict entry."""
    return obj.max if _is_typed_param(obj) else obj["max"]


def param_default(obj: Any) -> Any:
    """Return the default value from either a typed param or a dict entry."""
    return obj.default if _is_typed_param(obj) else obj["default"]


def param_coerce(obj: Any, raw: Any) -> Any:
    """Coerce *raw* to the parameter's native type.

    For typed params delegates to ``.coerce()``; for legacy dict entries
    mirrors the old ``type(default)(raw)`` behaviour.
    """
    if _is_typed_param(obj):
        return obj.coerce(raw)
    return type(obj["default"])(raw)


def param_validate(obj: Any, value: Any) -> None:
    """Validate *value* against the parameter's bounds or categories.

    Raises ValueError if out of range/invalid. Handles both typed and
    legacy dict-style entries.
    """
    if _is_typed_param(obj):
        obj.validate(value)
        return
    # Legacy dict entry — explicit range check (F-015)
    if value < obj["min"] or value > obj["max"]:
        raise ValueError(
            f"Value {value} out of range [{obj['min']}, {obj['max']}]"
        )


def param_to_dict(obj: Any) -> dict:
    """Convert a parameter entry to a JSON-safe dict for the server API.

    Typed params return ``.to_dict()``; legacy dict entries are returned
    as-is. This lets the ``GET /strategies/{name}/params`` endpoint handle
    both formats transparently.
    """
    if _is_typed_param(obj):
        return obj.to_dict()
    return dict(obj)
