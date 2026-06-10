import pytest

from village.registry import ContentDef, ContentRegistry, Registry


def test_register_and_get():
    reg = Registry("thing")
    item = ContentDef(id="a", name="A")
    assert reg.register(item) is item
    assert reg.get("a") is item
    assert "a" in reg
    assert len(reg) == 1


def test_duplicate_id_rejected():
    reg = Registry("thing")
    reg.register(ContentDef(id="a", name="A"))
    with pytest.raises(ValueError):
        reg.register(ContentDef(id="a", name="A2"))


def test_unknown_id():
    reg = Registry("thing")
    with pytest.raises(KeyError):
        reg.get("nope")


def test_type_check():
    reg = Registry("thing", base_type=ContentDef)
    with pytest.raises(TypeError):
        reg.register("not a content def")


def test_categories_are_shared():
    umbrella = ContentRegistry()
    a = umbrella.category("product")
    b = umbrella.category("product")
    assert a is b


def test_content_loads():
    from village.content import load_all
    from village.content.machines import MACHINES
    from village.content.products import PRODUCTS

    load_all(force=True)
    assert len(PRODUCTS) >= 5
    assert len(MACHINES) >= 4
    # Every machine input/output must reference a registered product.
    for m in MACHINES:
        for pid in list(m.inputs) + list(m.outputs):
            assert pid in PRODUCTS
