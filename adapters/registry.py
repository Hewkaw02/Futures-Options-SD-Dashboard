"""
Adapter Registry — Factory pattern for creating and managing adapters.

Usage:
    from adapters import AdapterRegistry

    # List all available providers
    AdapterRegistry.list_providers()

    # Create an adapter
    adapter = AdapterRegistry.get("databento", api_key="db-xxx")

    # Create from environment (reads .env automatically)
    adapter = AdapterRegistry.from_env("databento")
"""
import os
from typing import Optional
from .base import BaseDataAdapter, AssetClass


class AdapterRegistry:
    _adapters: dict[str, type[BaseDataAdapter]] = {}
    _env_keys: dict[str, list[str]] = {}  # provider -> required env vars

    @classmethod
    def register(cls, name: str, env_keys: Optional[list[str]] = None):
        """
        Decorator to register an adapter class.

        @AdapterRegistry.register("databento", env_keys=["DATABENTO_API_KEY"])
        class DatabentoAdapter(BaseDataAdapter):
            ...
        """
        def wrapper(adapter_cls):
            cls._adapters[name] = adapter_cls
            if env_keys:
                cls._env_keys[name] = env_keys
            return adapter_cls
        return wrapper

    @classmethod
    def get(cls, name: str, **kwargs) -> BaseDataAdapter:
        """Create an adapter instance by provider name."""
        if name not in cls._adapters:
            available = ", ".join(sorted(cls._adapters.keys()))
            raise ValueError(
                f"Unknown provider: '{name}'. "
                f"Available providers: [{available}]"
            )
        return cls._adapters[name](**kwargs)

    @classmethod
    def from_env(cls, name: str) -> BaseDataAdapter:
        """
        Create an adapter using credentials from environment variables.
        Reads from .env automatically via python-dotenv.
        """
        from dotenv import load_dotenv
        load_dotenv()

        if name not in cls._adapters:
            available = ", ".join(sorted(cls._adapters.keys()))
            raise ValueError(
                f"Unknown provider: '{name}'. "
                f"Available: [{available}]"
            )

        # Build kwargs from environment variables
        kwargs = {}
        env_keys = cls._env_keys.get(name, [])
        for key in env_keys:
            val = os.getenv(key)
            if val:
                # Convert ENV_VAR_NAME to kwarg_name
                param = key.lower()
                # Strip provider prefix if present
                prefixes = [f"{name}_", name.replace('-', '_') + "_"]
                for prefix in prefixes:
                    if param.startswith(prefix):
                        param = param[len(prefix):]
                        break
                kwargs[param] = val

        return cls._adapters[name](**kwargs)

    @classmethod
    def list_providers(cls) -> list[str]:
        """List all registered provider names."""
        return sorted(cls._adapters.keys())

    @classmethod
    def list_by_asset_class(cls, asset_class: AssetClass) -> list[str]:
        """List providers that support a specific asset class."""
        result = []
        for name, adapter_cls in cls._adapters.items():
            try:
                instance = adapter_cls.__new__(adapter_cls)
                if instance.get_asset_class() == asset_class:
                    result.append(name)
            except Exception:
                pass
        return sorted(result)

    @classmethod
    def get_provider_info(cls, name: str) -> dict:
        """Get provider capabilities and required env vars."""
        if name not in cls._adapters:
            raise ValueError(f"Unknown provider: '{name}'")
        return {
            "name": name,
            "env_keys": cls._env_keys.get(name, []),
            "adapter_class": cls._adapters[name].__name__,
        }

    @classmethod
    def list_all_info(cls) -> list[dict]:
        """Get info for all registered providers."""
        return [cls.get_provider_info(n) for n in cls.list_providers()]
