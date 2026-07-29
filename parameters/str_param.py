from parameters import Param


class StrParam(Param):
    def __init__(self, view: str, value: str = ""):
        super().__init__(view)
        self.value: str = value

    def value_repr(self) -> str:
        return self.value

    def set_value(self, value: str):
        self.value = value
