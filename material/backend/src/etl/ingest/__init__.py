import importlib
import pkgutil

# helper to automatically import all submodules for auto-registration in factory pattern.
for module_info in pkgutil.iter_modules(__path__):
    importlib.import_module(f"{__name__}.{module_info.name}")
