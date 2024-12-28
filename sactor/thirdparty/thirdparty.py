from abc import ABC, abstractmethod

class ThirdParty(ABC):
    def __init__(self):
        pass

    @staticmethod
    @abstractmethod
    def check_requirements() -> list[str]:
        pass

