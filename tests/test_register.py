import json
from pathlib import Path

import pytest

from village import register
from village.content import DEMANDS, MACHINES, PRODUCTS, RECIPES, load_all


def test_local_content_loads():
    load_all(force=True)
    assert len(PRODUCTS) >= 5
    assert len(MACHINES) >= 4
    assert len(DEMANDS) >= 1
    # Every machine recipe must exist; every recipe's products must exist,
    # and every buildable machine must itself be a product (its kit).
    for m in MACHINES:
        for rid in m.recipes:
            assert rid in RECIPES
        # Natural buildings are raised from land+coin; everything else
        # must exist as a purchasable kit product.
        if not m.natural:
            assert m.id in PRODUCTS
    for r in RECIPES:
        for pid in list(r.inputs) + list(r.outputs):
            assert pid in PRODUCTS
    # Every demand must be fulfillable by registered products.
    for d in DEMANDS:
        assert d.urgency.need >= d.urgency.want
        for pid in d.fulfilled_by:
            assert pid in PRODUCTS


def test_unknown_id_raises():
    load_all(force=True)
    with pytest.raises(KeyError):
        PRODUCTS.get("nope")


def _write_product(folder: Path, pid: str, price: int) -> None:
    sub = folder / "ProductDef"
    sub.mkdir(parents=True, exist_ok=True)
    (sub / f"{pid}.json").write_text(json.dumps({
        "id": pid, "name": pid.title(), "base_price": price,
        "color": [1, 2, 3]}))


def test_mod_overrides_local(tmp_path):
    base, mod = tmp_path / "base", tmp_path / "mod"
    _write_product(base, "grain", 2)
    _write_product(mod, "grain", 99)   # same id, loaded later -> overrides
    _write_product(mod, "salt", 5)     # new content from a mod
    reg = register.register_content([base, mod])
    assert reg["ProductDef"]["grain"].base_price == 99
    assert "salt" in reg["ProductDef"]


def test_meta_and_unknown_folders_skipped(tmp_path):
    _write_product(tmp_path, "grain", 2)
    (tmp_path / "meta").mkdir()
    (tmp_path / ".hidden").mkdir()
    (tmp_path / "NotAModel").mkdir()
    (tmp_path / "NotAModel" / "x.json").write_text("{}")
    reg = register.register_content([tmp_path])
    assert list(reg["ProductDef"]) == ["grain"]
    assert "NotAModel" not in reg


def test_invalid_json_does_not_abort(tmp_path, capsys):
    _write_product(tmp_path, "grain", 2)
    sub = tmp_path / "ProductDef"
    (sub / "broken.json").write_text("{not json")
    reg = register.register_content([tmp_path])
    assert "grain" in reg["ProductDef"]
    assert "Error parsing" in capsys.readouterr().out
