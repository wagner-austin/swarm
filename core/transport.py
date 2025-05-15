from abc import ABC, abstractmethod

class Transport(ABC):
    """
    Abstract base class for bot transport layers (Signal, Discord, etc).
    """
    @abstractmethod
    async def send_message(self, *args, **kwargs):
        pass

    @abstractmethod
    async def receive_messages(self, *args, **kwargs):
        pass
