from parameters import Param


class BoolParam(Param):
    def __init__(self, view: str, value: bool = False):
        super().__init__(view)
        self.value: bool = value

    def __bool__(self):
        return self.value

    def value_repr(self) -> str:
        return "Включено" if self.value else "Отключено"

    def set_value(self, value: str):
        from_repr = value == "Включено"
        from_str = value == "True"
        from_conf = value == "true"
        self.value = from_repr or from_str or from_conf
