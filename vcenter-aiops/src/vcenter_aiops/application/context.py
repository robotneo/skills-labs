from contextlib import contextmanager
from dataclasses import dataclass
from ..infrastructure.config import Profiles
from ..infrastructure.paths import data_home
from ..infrastructure.store import Store


@dataclass
class Context:
    profile: str | None = None
    timeout: int = 30

    @property
    def home(self):
        return data_home()

    @property
    def profiles(self):
        return Profiles(self.home)

    @property
    def secrets(self):
        from ..infrastructure.secrets import SecretVault
        return SecretVault(data_home(preserve_links=True))

    @contextmanager
    def store(self):
        store = Store(self.home / "state.db")
        try:
            yield store
        finally:
            store.close()

    @contextmanager
    def session(self):
        from ..providers.vsphere.connection import Session
        with Session(self.profiles.get(self.profile), self.timeout) as si:
            yield si
