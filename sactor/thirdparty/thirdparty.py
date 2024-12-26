from abc import ABC, abstractmethod

class ThirdParty(ABC):
    def __init__(self):
        pass

    @abstractmethod
    def check_dependency() -> bool:
        pass

