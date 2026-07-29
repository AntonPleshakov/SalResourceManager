from abc import ABC, abstractmethod
from typing import Dict, List

from db.gapi.worksheet_manager import Matrix


class Param(ABC):
    def __init__(self, view: str):
        self.view: str = view
        self.index: int = -1

    def value_repr(self) -> str:
        pass

    def __str__(self):
        return self.value_repr()

    def __eq__(self, other):
        return self.value_repr() == other.value_repr()

    @abstractmethod
    def set_value(self, value: str):
        pass


class Parameters:
    def __new__(cls, *args, **kwargs):
        instance = super().__new__(cls)
        instance._index_ctr = 0
        return instance

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

    def to_matrix(self) -> Matrix:
        result: Matrix = []
        for param in self.params().values():
            result.append([param.view, param.value_repr()])
        return result

    @classmethod
    def from_matrix(cls, matrix: Matrix):
        parameters = cls()
        view_to_name = {param.view: name for name, param in parameters.params().items()}
        for row in matrix:
            if len(row) == 2 and row[0] in view_to_name:
                parameters.set_value(view_to_name[row[0]], row[1])
        return parameters

    def to_row(self) -> List[str]:
        return [param.value_repr() for param in self.params().values()]

    @classmethod
    def from_row(cls, row: List[any]):
        parameters = cls()
        for attr, value in zip(parameters.params(), row):
            parameters.set_value(attr, value)
        return parameters

    def view(self):
        text = ""
        for param in self.params().values():
            text += f"{param.view}: {param.value_repr()}\n"
        return text

    def set_value(self, attr_name: str, value: any):
        if isinstance(value, str):
            getattr(self, attr_name).set_value(value)
        elif isinstance(value, Param):
            getattr(self, attr_name).set_value(value.value_repr())
        else:
            getattr(self, attr_name).value = value

    def get_value(self, attr_name):
        return getattr(self, attr_name).value_repr()
