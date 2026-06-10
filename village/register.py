# village/register.py
"""
Content registry, ported from the original project's register.py.

Scans the local `content/` directory plus any mod folders under
`content_custom/`, loads all JSON definitions into Pydantic models, and
registers them in a central registry. Ignores any subfolder named "meta" or
starting with a dot.

Layout: each subfolder of a content source is named after a Pydantic model
class in `village/objects.py`; every ``*.json`` file inside it is validated
into that model. Models with an `id` field are stored in a dict by id,
overriding earlier definitions when duplicates occur (so mods override local
content); other models are stored in lists.
"""
import inspect
import json
from pathlib import Path
from typing import Dict, List, Type, Union

from pydantic import BaseModel

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# Local content directory
LOCAL_CONTENT = PROJECT_ROOT / "content"
# Mod content sources: every valid subfolder of content_custom/
MOD_ROOT = PROJECT_ROOT / "content_custom"

REGISTRY: Dict[str, Union[List[BaseModel], Dict[str, BaseModel]]] = {}


def is_valid_folder(path: Path) -> bool:
    return (
        path.is_dir()
        and not path.name.startswith('.')
        and path.name != 'meta'
    )


def load_models() -> Dict[str, Type[BaseModel]]:
    """
    Import all Pydantic model classes from village/objects.py.
    Returns a mapping of model_name -> class.
    """
    from . import objects as objs_mod

    models: Dict[str, Type[BaseModel]] = {}
    for name, cls in inspect.getmembers(objs_mod, inspect.isclass):
        if issubclass(cls, BaseModel) and cls is not BaseModel:
            models[name] = cls
    return models


def register_content(folders: List[Path]) -> Dict[str, Union[List[BaseModel], Dict[str, BaseModel]]]:
    """
    Load all JSON files in each valid subfolder of the given folders,
    parse them with the corresponding Pydantic model based on folder name,
    and collect them into a registry dict:
      - For models with an `id` field: { model_name: { id: instance, ... } }
      - For others: { model_name: [instance, ...] }
    """
    models = load_models()
    # Determine which models use `id` as a key
    id_models = {name for name, cls in models.items()
                 if 'id' in getattr(cls, 'model_fields', {})}

    # Initialize registry with appropriate structures
    registry: Dict[str, Union[List[BaseModel], Dict[str, BaseModel]]] = {}
    for name in models:
        if name in id_models:
            registry[name] = {}
        else:
            registry[name] = []

    # Load in order: local content first, then mods (mods override)
    for folder in folders:
        if not folder.exists():
            continue
        for sub in folder.iterdir():
            if not is_valid_folder(sub):
                continue
            model_name = sub.name
            model_cls = models.get(model_name)
            if model_cls is None:
                # skip unknown model folders
                continue
            # Scan JSON files in this model's folder
            for json_file in sorted(sub.glob("*.json")):
                try:
                    data = json.loads(json_file.read_text(encoding="utf-8"))
                    instance = model_cls.model_validate(data)
                    if model_name in id_models:
                        key = getattr(instance, 'id')
                        registry[model_name][key] = instance
                    else:
                        registry[model_name].append(instance)  # type: ignore
                except Exception as e:
                    print(f"Error parsing {json_file}: {e}")

    return registry


def default_sources() -> List[Path]:
    mods = ([p for p in sorted(MOD_ROOT.iterdir()) if is_valid_folder(p)]
            if MOD_ROOT.exists() else [])
    return [LOCAL_CONTENT] + mods


def load(sources: List[Path] = None) -> None:
    """Populate the global REGISTRY from the given (or default) sources."""
    global REGISTRY
    REGISTRY = register_content(sources if sources is not None
                                else default_sources())


def main():
    load()
    # Summary output
    for model_name, collection in REGISTRY.items():
        print(f"Loaded {len(collection)} {model_name} entries.")


if __name__ == "__main__":
    main()
