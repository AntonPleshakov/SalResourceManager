from abc import ABC, abstractmethod
from typing import Dict, List


def raw_parameter_value(parameter):
    return parameter.value


class Param(ABC):
    def __init__(self, view: str):
        self.view: str = view
        self.index: int = -1

    @abstractmethod
    def value_repr(self) -> str:
        raise NotImplementedError("Parameter string representation is required")

    def __str__(self):
        return self.value_repr()

    def __eq__(self, other):
        return self.value_repr() == other.value_repr()

    @abstractmethod
    def set_value(self, _):
        raise NotImplementedError("Parameter value conversion is required")


class Parameters:
    def __init__(self) -> None:
        self._index_ctr = 0

    def __setattr__(self, key, value):
        if isinstance(value, Param) and value.index == -1:
            value.index = self._index_ctr
            self._index_ctr += 1
        super().__setattr__(key, value)

    def params(self) -> Dict[str, Param]:
        result = {}
        for name, value in vars(self).items():
            if isinstance(value, Param):
                result[name] = value
        return result

    def params_views(self) -> List[str]:
        return [param.view for param in self.params().values()]

    def __eq__(self, other):
        for param in self.params():
            if getattr(self, param) != getattr(other, param):
                return False
        return True

    def to_row(self) -> List[str]:
        return [param.value_repr() for param in self.params().values()]

    @classmethod
    def from_row(cls, row: List[any]):
        parameters = cls()
        for attr, value in zip(parameters.params(), row):
            parameters.set_value(attr, value)
        return parameters

    def set_value(self, attr_name: str, value: any):
        if isinstance(value, str):
            getattr(self, attr_name).set_value(value)
        elif isinstance(value, Param):
            getattr(self, attr_name).set_value(value.value_repr())
        else:
            getattr(self, attr_name).value = value

    def get_value(self, attr_name):
        return getattr(self, attr_name).value_repr()
