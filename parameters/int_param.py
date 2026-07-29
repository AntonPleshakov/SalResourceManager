from parameters import Param


class IntParam(Param):
    def __init__(self, view: str, value: int = 0):
        super().__init__(view)
        self.value: int = value

    def __int__(self):
        return self.value

    def value_repr(self) -> str:
        return str(self.value)

    def set_value(self, value: str):
        self.value = int(value)
