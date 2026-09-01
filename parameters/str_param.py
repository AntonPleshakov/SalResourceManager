from parameters import Param, raw_parameter_value


class StrParam(Param):
    def __init__(self, view: str, value: str = ""):
        super().__init__(view)
        self.value: str = value

    value_repr = raw_parameter_value

    def set_value(self, value: str):
        self.value = value
