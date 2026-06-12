"""Sidebar: inspect a parcel, build/upgrade/demolish machines, set prices,
and trade parcels on the land market."""

from __future__ import annotations

from typing import Callable, Optional

import pygame

from ..content import DEMANDS, MACHINES, PRODUCTS, VEHICLES
from ..sim.money import cents, fmt
from ..sim import config as config_mod
from ..sim.plot import Plot
from ..sim.world import World
from . import assets
from .widgets import ButtonBank


def _io(d: dict) -> str:
    return " + ".join(f"{q} {PRODUCTS.get(p).name}" for p, q in d.items())


def recipe_line(rdef) -> str:
    return f"{_io(rdef.inputs) or 'nothing'} -> {_io(rdef.outputs)}"


def machine_def_text(mdef) -> str:
    if mdef.resells:
        st = mdef.storage
        extra = f" (+{st.weight:.0f} wt storage)" if st else ""
        return f"resells stored goods{extra}"
    from ..content import RECIPES
    names = [RECIPES.get(r).name for r in mdef.recipes]
    return "makes: " + ", ".join(names[:4]) + ("..." if len(names) > 4 else "")


def io_text(io: dict) -> str:
    if not io:
        return "nothing"
    return ", ".join(f"{q} {PRODUCTS.get(p).name}" for p, q in sorted(io.items()))


def machine_tooltip(machine) -> list:
    """Hover detail for a machine: yesterday's consumption/production."""
    r = machine.recipe()
    lines = [f"{machine.definition.name}  Lv{machine.level}"
             + (f" -- {r.name}" if r else ""),
             f"Uptime (7d): {machine.uptime():.0%}"]
    if machine.history:
        day = machine.history[-1]
        lines += [f"Yesterday  (ran {day.uptime:.0%} of the day)",
                  f"  consumed: {io_text(day.consumed)}",
                  f"  produced: {io_text(day.produced)}"]
    else:
        lines.append("(no full day recorded yet)")
    if machine.stalled:
        lines.append("Stalled: parcel storage is full")
    elif machine.paused:
        lines.append("Paused: stock covers current demand")
    elif machine.output_capped():
        lines.append("Holding: stockpile/storage at its configured cap")
    if machine.operator_id is not None:
        lines.append("Operator pinned (see Manage)")
    if not machine.auto_buy:
        lines.append("Auto-buy off: runs on supplied materials only")
    return lines


def product_tooltip(owner, pid) -> list:
    """Hover detail for a good on sale: yesterday's economics."""
    name = PRODUCTS.get(pid).name
    day = owner.yesterday(pid)
    if day is None:
        return [f"{name} -- yesterday", "(no full day recorded yet)"]
    return [f"{name} -- yesterday",
            f"  profit: {fmt(day.profit)}  "
            f"({day.sold} sales for {fmt(day.revenue)})",
            f"  produced: {day.produced}",
            f"  consumed by own machines: {day.consumed}"]


class BuildingPanel:
    def __init__(self, rect: pygame.Rect, font: pygame.font.Font,
                 small_font: pygame.font.Font, buttons: ButtonBank,
                 notify: Callable[[str], None]):
        self.rect = rect
        self.font = font
        self.small_font = small_font
        self.buttons = buttons
        self.notify = notify
        self.build_slot: Optional[int] = None  # slot picking a machine to build
        self.manage_machine = None  # machine whose crew/policy menu is open
        self.craft_open = False     # parcel craft menu (run any local recipe)
        self.move_pid: Optional[str] = None  # product being moved off-parcel
        self.move_qty_i = 0                  # index into MOVE_QTYS
        self.app_hooks = None  # set by App; lets panel open the buy menu
        # (rect, lines) hover tooltips, rebuilt every frame during draw.
        self.hover_zones: list = []

    # --- text helpers -------------------------------------------------------
    def _line(self, screen, text: str, y: int, color=assets.PANEL_TEXT,
              small: bool = False, x_off: int = 12) -> int:
        font = self.small_font if small else self.font
        surf = font.render(text, True, color)
        screen.blit(surf, (self.rect.x + x_off, y))
        return y + surf.get_height() + 4

    def _header(self, screen, text: str, y: int) -> int:
        y += 6
        y = self._line(screen, text, y, color=assets.PANEL_DIM)
        pygame.draw.line(screen, assets.PANEL_DIM,
                         (self.rect.x + 10, y), (self.rect.right - 10, y))
        return y + 6

    # --- drawing -------------------------------------------------------------
    def draw(self, screen: pygame.Surface, world: World,
             plot: Optional[Plot]) -> None:
        self.hover_zones.clear()
        pygame.draw.rect(screen, assets.PANEL_BG, self.rect)
        pygame.draw.line(screen, assets.PANEL_DIM, self.rect.topleft,
                         self.rect.bottomleft)
        if plot is None:
            self._line(screen, "Click a parcel to inspect it.",
                       self.rect.y + 16, color=assets.PANEL_DIM)
            return
        if plot.owner_id is None:
            self._draw_unowned(screen, world, plot)
            return

        owner = world.people[plot.owner_id]
        mine = owner.is_player
        y = self.rect.y + 12
        title = "Your parcel" if mine else f"{owner.name}'s parcel"
        if plot is owner.home:
            title += "  (home)"
        y = self._line(screen, title, y)
        y = self._line(screen, f"Coin: {fmt(owner.money)}", y,
                       color=assets.PLAYER_BORDER if mine else assets.PANEL_TEXT)
        demands = "  |  ".join(
            f"{d.name} {owner.demands.get(d.id, 0):.0f}" for d in DEMANDS)
        y = self._line(screen, f"Knows {len(owner.knowledge)} people  |  "
                       f"{demands}", y, small=True, color=assets.PANEL_DIM)
        uw, us = plot.used()
        cw, cs = plot.capacity()
        y = self._line(screen,
                       f"Storage: {uw:.0f}/{cw:.0f} wt   {us:.0f}/{cs:.0f} sp",
                       y, small=True, color=assets.PANEL_DIM)
        if mine:
            y = self._line(screen, "Your auto-buy reaches the whole village",
                           y, small=True, color=assets.PLAYER_BORDER)
            def open_buy(p=plot):
                app = self.app_hooks
                if app is not None:
                    app.buy_menu.open_for(p)
                    app.show_buy = True
            self.buttons.draw(screen,
                              pygame.Rect(self.rect.x + 12, y, 200, 20),
                              "Open buy menu (deliver here)", open_buy)
            y += 26
        y = self._draw_land_market(screen, world, owner, plot, y)

        if self.build_slot is not None and mine:
            self._draw_build_menu(screen, world, owner, plot, y)
            return
        if self.manage_machine is not None and mine:
            if self.manage_machine in plot.machines():
                self._draw_machine_menu(screen, world, owner, plot, y)
                return
            self.manage_machine = None  # demolished or elsewhere
        if self.craft_open and mine:
            self._draw_craft_menu(screen, world, owner, plot, y)
            return
        if self.move_pid is not None and mine:
            if plot.inventory.get(self.move_pid, 0) > 0:
                self._draw_move_menu(screen, world, owner, plot, y)
                return
            self.move_pid = None  # stack gone; fall through

        y = self._header(screen, "MACHINES", y)
        for i, machine in enumerate(plot.slots):
            y = self._draw_slot(screen, world, owner, plot, i, machine, y, mine)
        if mine and any(m.definition.recipes for m in plot.machines()):
            def open_craft():
                self.craft_open = True
            self.buttons.draw(screen,
                              pygame.Rect(self.rect.x + 12, y, 240, 20),
                              "Craft menu (run any recipe here)", open_craft)
            y += 26

        y = self._draw_vehicles(screen, world, owner, plot, y, mine)
        y = self._draw_staff(screen, world, owner, y, mine)
        if mine:
            y = self._draw_crafting(screen, world, owner, plot, y)
            y = self._draw_advertising(screen, world, owner, plot, y)

        y = self._header(screen, "GOODS FOR SALE (all parcels)", y)
        produced = sorted(owner.produced_products())
        if not produced:
            y = self._line(screen, "(nothing produced)", y,
                           color=assets.PANEL_DIM, small=True)
        for pid in produced:
            prod = PRODUCTS.get(pid)
            stock = owner.stock(pid)
            price = owner.price_of(pid)
            y0 = y
            y = self._line(screen,
                           f"{prod.name}: {stock} in stock @ {fmt(price)}",
                           y, small=True)
            self.hover_zones.append((
                pygame.Rect(self.rect.x, y0, self.rect.w, y - y0),
                product_tooltip(owner, pid)))
            if mine:
                def make_adj(p=pid, delta=0):
                    def adj():
                        owner.prices[p] = max(1, owner.price_of(p) + delta)
                    return adj
                auto = pid in owner.auto_prices
                def toggle_auto(p=pid):
                    if p in owner.auto_prices:
                        owner.auto_prices.discard(p)
                        self.notify("Manual pricing")
                    else:
                        owner.auto_prices.add(p)
                        self.notify("Price follows the market daily")
                bx = self.rect.right - 156
                self.buttons.draw(screen, pygame.Rect(bx, y0, 22, 18),
                                  "A" if auto else "a", toggle_auto)
                bx += 26
                for label, delta, w in (("--", -25, 28), ("-", -1, 22),
                                        ("+", +1, 22), ("++", +25, 28)):
                    self.buttons.draw(screen, pygame.Rect(bx, y0, w, 18),
                                      label, make_adj(pid, delta),
                                      enabled=not auto)
                    bx += w + 4

        y = self._header(screen, "PARCEL INVENTORY", y)
        items = [(pid, qty) for pid, qty in sorted(plot.inventory.items())
                 if qty > 0]
        if not items:
            y = self._line(screen, "(empty)", y, color=assets.PANEL_DIM,
                           small=True)
        for pid, qty in items:
            y0 = y
            y = self._line(screen, f"{PRODUCTS.get(pid).name}: {qty}", y,
                           small=True)
            if mine:
                def open_move(p=pid):
                    self.move_pid = p
                    self.move_qty_i = 0
                def do_trash(p=pid, q=qty):
                    plot.inventory[p] = 0
                    self.notify(f"Discarded {q} {PRODUCTS.get(p).name}")
                bx = self.rect.right - 112
                self.buttons.draw(screen, pygame.Rect(bx, y0, 50, 17),
                                  "Move", open_move)
                self.buttons.draw(screen, pygame.Rect(bx + 54, y0, 50, 17),
                                  "Trash", do_trash)

    # --- land market ----------------------------------------------------------
    def _draw_unowned(self, screen, world: World, plot: Plot) -> None:
        y = self.rect.y + 12
        y = self._line(screen, "Unowned parcel", y)
        price = world.plot_sale_price(plot)
        y = self._line(screen, f"Price: {fmt(price)}", y,
                       color=assets.PLAYER_BORDER)
        y = self._line(screen, "Common land. Anyone may buy it", y,
                       small=True, color=assets.PANEL_DIM)
        player = world.player
        def do_buy():
            if world.buy_plot(player, plot):
                self.notify("Bought the parcel")
            else:
                self.notify("Not enough coin")
        self.buttons.draw(screen,
                          pygame.Rect(self.rect.x + 12, y + 6, 130, 22),
                          f"Buy for {fmt(price)}", do_buy,
                          enabled=player.money >= price)

    def _draw_land_market(self, screen, world: World, owner, plot: Plot,
                          y: int) -> int:
        player = world.player
        mine = owner.is_player
        if plot.for_sale_price is not None:
            y = self._line(screen,
                           f"FOR SALE: {fmt(plot.for_sale_price)}", y,
                           color=assets.PLAYER_BORDER)
            if mine:
                def do_unlist():
                    world.unlist_plot(owner, plot)
                    self.notify("Parcel taken off the market")
                self.buttons.draw(screen,
                                  pygame.Rect(self.rect.x + 12, y, 90, 20),
                                  "Unlist", do_unlist)
                y += 26
            else:
                price = plot.for_sale_price
                def do_buy():
                    if world.buy_plot(player, plot):
                        self.notify(f"Bought {owner.name}'s parcel")
                    else:
                        self.notify("Not enough coin")
                self.buttons.draw(screen,
                                  pygame.Rect(self.rect.x + 12, y, 130, 20),
                                  f"Buy for {fmt(price)}", do_buy,
                                  enabled=player.money >= price)
                y += 26
        elif mine and plot is not owner.home and not plot.machines():
            def do_list():
                if world.list_plot(owner, plot):
                    self.notify("Parcel listed for sale")
            self.buttons.draw(screen,
                              pygame.Rect(self.rect.x + 12, y, 160, 20),
                              f"Sell parcel ({fmt(config_mod.PARCEL_PRICE)})",
                              do_list)
            y += 26
        return y

    # --- vehicles ---------------------------------------------------------------
    def _draw_vehicles(self, screen, world: World, owner, plot, y: int,
                       mine: bool) -> int:
        y = self._header(screen, "VEHICLES (fleet)", y)
        for v in owner.vehicles:
            d = v.definition
            here = v.plot is plot
            where = "here" if here else f"@ parcel {v.plot.id}"
            line = (f"{d.name} [{where}]: {v.status(world.tick_count)}"
                    f"  |  fuel due {v.fuel_due:.0f}")
            y0 = y
            y = self._line(screen, line, y, small=True)
            self.hover_zones.append((
                pygame.Rect(self.rect.x, y0, self.rect.w, y - y0),
                [f"{d.name}  ({v.trips} trips)",
                 f"cargo: {d.cargo.weight:.0f} wt / {d.cargo.space:.0f} sp",
                 f"trip cost: ${d.cost.base:.2f} base"
                 f" + ${d.cost.tile:.2f}/tile",
                 f"speed: {d.speed.base:.0f} tiles/h (less when loaded)"]))
        if mine:
            from ..sim import trade as trade_mod
            for d in VEHICLES:
                craftable = d.id in PRODUCTS
                kits_here = plot.inventory.get(d.id, 0) if craftable else 0
                if not craftable:
                    label = f"Hire {d.name} ({fmt(cents(d.buy_cost))})"
                    enabled = owner.money >= cents(d.buy_cost)
                elif kits_here:
                    label = f"Commission {d.name} (kit here)"
                    enabled = True
                else:
                    quote = trade_mod.best_quote(world, owner, d.id, 1, plot)
                    label = (f"Order {d.name} kit "
                             f"({fmt(int(quote.unit_cost))})" if quote
                             else f"Request {d.name} kit")
                    enabled = True
                def do_buy(vd=d, p=plot, ch=kits_here, cr=craftable):
                    if not cr or ch:
                        if world.buy_vehicle(owner, vd.id, p) is not None:
                            self.notify(f"{vd.name} in service (parked here)")
                        else:
                            self.notify("Couldn't commission it")
                    else:
                        if trade_mod.buy(world, owner, vd.id, qty=1, dest=p):
                            self.notify(f"{vd.name} kit ordered")
                        else:
                            self.notify("None for sale -- workshops will "
                                        "hear of your request")
                self.buttons.draw(
                    screen, pygame.Rect(self.rect.x + 12, y, 220, 18),
                    label, do_buy, enabled=enabled)
                y += 22
        return y + 4

    # --- staff -------------------------------------------------------------------
    def _draw_staff(self, screen, world: World, owner, y: int,
                    mine: bool) -> int:
        y = self._header(screen, "STAFF", y)
        if owner.employer_id is not None:
            boss = world.people.get(owner.employer_id)
            y = self._line(screen,
                           f"Works for {boss.name if boss else '?'}"
                           f" ({fmt(config_mod.WAGE_PER_DAY)}/day)",
                           y, small=True)
        for sid in list(owner.staff):
            worker = world.people.get(sid)
            if worker is None:
                continue
            status = ("out driving" if worker.is_busy(world.tick_count)
                      else "on the floor")
            best = max(worker.skills.items(), key=lambda kv: kv[1],
                       default=None)
            skill = (f"{best[0]} {best[1]:.0%}" if best else "unskilled")
            y0 = y
            y = self._line(screen,
                           f"{worker.name} ({skill}) "
                           f"{fmt(worker.wage)}/d: {status}",
                           y, small=True)
            if mine:
                def do_fire(wid=sid):
                    world.fire(owner, wid)
                    self.notify("Let them go")
                self.buttons.draw(screen,
                                  pygame.Rect(self.rect.right - 58, y0, 46, 16),
                                  "Fire", do_fire)
        if not owner.staff and owner.employer_id is None:
            y = self._line(screen, "(works alone)", y,
                           color=assets.PANEL_DIM, small=True)
        if mine:
            y = self._line(screen,
                           f"Cost of living: {fmt(world.cost_of_living())}"
                           f"/day", y, small=True, color=assets.PANEL_DIM)
            y = self._line(screen, "(wages below it won't draw settlers)",
                           y, small=True, color=assets.PANEL_DIM)
            postings = [j for j in world.job_postings
                        if j.employer_id == owner.id]
            if postings:
                y = self._line(screen,
                               f"{len(postings)} job posting(s) open "
                               f"(manage at the machine)",
                               y, small=True, color=assets.PLAYER_BORDER)
            def do_hire():
                worker = world.hire(owner, world.missing_skill(owner))
                if worker is None:
                    worker = world.hire(owner)
                if worker is not None:
                    self.notify(f"Hired {worker.name} "
                                f"({fmt(config_mod.WAGE_PER_DAY)}/day)")
                else:
                    self.notify("Nobody's looking for work")
            self.buttons.draw(screen,
                              pygame.Rect(self.rect.x + 12, y, 200, 18),
                              f"Hire ({fmt(config_mod.WAGE_PER_DAY)}/day)",
                              do_hire)
            y += 24
        return y + 4

    # --- hand crafting -------------------------------------------------------------
    def _draw_crafting(self, screen, world: World, owner, plot, y: int) -> int:
        from ..content import RECIPES
        y = self._header(screen, "HAND-CRAFT (kits; takes your time)", y)
        if owner.is_busy(world.tick_count):
            return self._line(
                screen, f"busy for {owner.busy_until - world.tick_count}t",
                y, small=True, color=assets.PANEL_DIM)
        shown = 0
        for r in RECIPES:
            ok_outputs = all(any(t in ("machine-kit", "vehicle-kit")
                                 for t in PRODUCTS.get(p).tags)
                             for p in r.outputs)
            if not ok_outputs:
                continue
            have = all(plot.inventory.get(p, 0) >= q
                       for p, q in r.inputs.items())
            if not have:
                continue
            io = " + ".join(f"{q} {PRODUCTS.get(p).name}"
                            for p, q in r.inputs.items())
            y0 = y
            y = self._line(screen, f"{r.name}  ({io}, {r.base_ticks}t)",
                           y, small=True)
            def do_craft(rid=r.id, p=plot):
                if world.craft(owner, p, rid):
                    self.notify("Crafted -- you'll be busy a while")
                else:
                    self.notify("Can't craft right now")
            self.buttons.draw(screen,
                              pygame.Rect(self.rect.right - 64, y0, 52, 17),
                              "Craft", do_craft)
            shown += 1
            if shown >= 4:
                break
        if not shown:
            y = self._line(screen, "(gather materials, e.g. wood)", y,
                           small=True, color=assets.PANEL_DIM)
        return y + 4

    # --- advertising -------------------------------------------------------------
    def _draw_advertising(self, screen, world: World, owner, plot, y) -> int:
        from ..content import ADVERTS
        from ..sim import ads as ads_mod
        y = self._header(screen, "ADVERTISING (from this parcel)", y)
        for addef in ADVERTS:
            y0 = y
            ok = ads_mod.ready(world, owner, addef)
            wait = owner.ad_cooldowns.get(addef.id, 0) - world.day
            label = (f"{addef.name} ({fmt(cents(addef.cost))})" if ok
                     else f"{addef.name} (ready in {wait}d)")
            def do_run(a=addef, p=plot):
                got = ads_mod.run_ad(world, owner, a, p)
                if got is None:
                    self.notify("Can't run that campaign yet")
                else:
                    self.notify(f"{a.name}: {got} villagers heard of you")
            self.buttons.draw(
                screen, pygame.Rect(self.rect.x + 12, y, 220, 18),
                label, do_run,
                enabled=ok and owner.money >= cents(addef.cost))
            zone = pygame.Rect(self.rect.x, y0, self.rect.w, 22)
            local = (f"local (falloff {addef.falloff:.0f} tiles)"
                     if addef.falloff is not None else "village-wide")
            self.hover_zones.append((zone, [
                addef.name,
                f"reach {addef.reach} people, {local}",
                f"cooldown {addef.cooldown_days}d",
                addef.description]))
            y += 22
        return y + 4

    # --- machines --------------------------------------------------------------
    def _draw_slot(self, screen, world: World, owner, plot: Plot, index: int,
                   machine, y: int, mine: bool) -> int:
        if machine is None:
            y0 = y
            y = self._line(screen, f"Slot {index + 1}: empty", y,
                           color=assets.PANEL_DIM, small=True)
            if mine:
                def open_build(i=index):
                    self.build_slot = i
                self.buttons.draw(
                    screen, pygame.Rect(self.rect.right - 70, y0, 58, 18),
                    "Build", open_build)
            return y + 4

        d = machine.definition
        if machine.stalled:
            status = "full"
        elif machine.paused:
            status = "paused"
        elif machine.batches:
            status = f"running x{machine.batches}"
        elif d.resells:
            status = "open"
        elif machine.output_capped():
            status = "holding"
        else:
            status = "idle"
        if machine.priority:
            status += f", pri {machine.priority}"
        y0 = y
        y = self._line(screen,
                       f"{d.name}  Lv{machine.level}  ({status})", y)
        r = machine.recipe()
        desc = (f"{r.name}: {recipe_line(r)} ({machine.cycle_ticks}t)"
                if r is not None else machine_def_text(d))
        y = self._line(screen,
                       f"{desc}   |   up {machine.uptime():.0%}",
                       y, small=True, color=assets.PANEL_DIM)
        if mine and len(d.recipes) > 1:
            def do_switch(m=machine):
                opts = m.definition.recipes
                cur = opts.index(m.active_recipe)
                nxt = opts[(cur + 1) % len(opts)]
                if m.set_recipe(nxt):
                    from ..content import RECIPES as _R
                    self.notify(f"Now making: {_R.get(nxt).name}")
                else:
                    self.notify("Finish the current batch first")
            self.buttons.draw(screen,
                              pygame.Rect(self.rect.right - 88, y0, 76, 18),
                              "Recipe >", do_switch)
        self.hover_zones.append((
            pygame.Rect(self.rect.x, y0, self.rect.w, y - y0),
            machine_tooltip(machine)))
        if mine:
            bx = self.rect.x + 12
            row = pygame.Rect(bx, y, 116, 20)
            if machine.can_upgrade:
                cost = machine.upgrade_cost
                def do_upgrade(m=machine):
                    if world.upgrade_machine(owner, m):
                        self.notify(f"Upgraded {m.definition.name} to "
                                    f"Lv{m.level}")
                    else:
                        self.notify("Not enough coin to upgrade")
                self.buttons.draw(screen, row, f"Upgrade {fmt(cost)}",
                                  do_upgrade, enabled=owner.money >= cost)
            else:
                self.buttons.draw(screen, row, "Max level", lambda: None,
                                  enabled=False)
            def do_demolish(i=index, name=d.name):
                world.demolish_machine(owner, plot, i)
                self.notify(f"Demolished {name}")
            self.buttons.draw(screen, pygame.Rect(bx + 122, y, 80, 20),
                              "Demolish", do_demolish)
            if r is not None:
                def open_manage(m=machine):
                    self.manage_machine = m
                self.buttons.draw(screen, pygame.Rect(bx + 208, y, 80, 20),
                                  "Manage", open_manage)
            y += 26
        return y + 4

    # --- machine crew & policy menu ------------------------------------------
    def _draw_machine_menu(self, screen, world: World, owner, plot: Plot,
                           y: int) -> None:
        from ..sim import config as cfg
        machine = self.manage_machine
        d = machine.definition
        x = self.rect.x + 12
        y = self._header(screen, f"MANAGE: {d.name.upper()}", y)
        skill = d.skill
        info = f"Needs {d.workers} operator(s)"
        if skill:
            info += f", skill: {skill}"
        y = self._line(screen, info, y, small=True, color=assets.PANEL_DIM)
        if skill:
            y = self._line(
                screen, f"Unqualified hands run it "
                f"{1 - cfg.UNQUALIFIED_SPEED:.0%} slower",
                y, small=True, color=assets.PANEL_DIM)

        if d.workers == 0:
            y = self._line(screen, "Runs itself -- no operators needed.",
                           y, small=True, color=assets.PANEL_DIM)
            y = self._draw_operation_policy(screen, machine, y)
            return

        # Operator: pin one of the on-site crew, or let staffing pick by
        # qualification each day.
        y = self._header(screen, "OPERATOR", y)
        def set_op(pid):
            machine.operator_id = pid
            self.notify("Operator assignment updated")
        cur = machine.operator_id
        self.buttons.draw(screen, pygame.Rect(x, y, 240, 18),
                          "Auto (best qualified first)"
                          + ("  *" if cur is None else ""),
                          lambda: set_op(None), enabled=cur is not None)
        y += 22
        crew = [owner] + [world.people[i] for i in owner.staff
                          if i in world.people]
        for p in crew:
            if skill:
                mastery = p.skills.get(skill, 0)
                tag = (f"{skill} {mastery:.0%}"
                       if mastery >= cfg.SKILL_MIN else "unqualified")
            else:
                tag = "ready"
            name = "You" if p.is_player else p.name
            label = f"{name} ({tag})" + ("  *" if cur == p.id else "")
            self.buttons.draw(screen, pygame.Rect(x, y, 240, 18), label,
                              lambda pid=p.id: set_op(pid),
                              enabled=cur != p.id)
            y += 22

        # Hiring: a posting tied to this machine's seat.
        y = self._header(screen, "HIRE FOR THIS MACHINE", y)
        y = self._line(screen,
                       f"Cost of living here: {fmt(world.cost_of_living())}"
                       f"/day", y, small=True, color=assets.PANEL_DIM)
        y = self._line(screen, "(a posting paying at least this can",
                       y, small=True, color=assets.PANEL_DIM)
        y = self._line(screen, "draw settlers from outside)",
                       y, small=True, color=assets.PANEL_DIM)
        posting = world.posting_for(machine)
        if posting is None:
            wage = world.suggested_wage(skill)
            def do_post():
                world.post_job(owner, machine, strict=True)
                self.notify("Job posted -- filled from the labor market "
                            "daily")
            self.buttons.draw(screen, pygame.Rect(x, y, 240, 20),
                              f"Post job @ {fmt(wage)}/day", do_post)
            y += 26
        else:
            y = self._line(screen, f"Open since day {posting.created_day}",
                           y, small=True)
            state, left = world.posting_immigration_status(posting)
            status = {
                "countdown": f"Drawing settlers: one arrives in ~"
                             f"{max(1, left)}d (unless filled locally)",
                "low_wage": "No settlers: wage is below the cost of living",
                "no_food": "No settlers: village food too scarce",
                "underfunded": "No settlers: you can't bankroll this wage",
                "no_room": "No settlers: no free parcel to settle on",
            }[state]
            y = self._line(screen, status, y, small=True,
                           color=assets.PLAYER_BORDER if state == "countdown"
                           else assets.PANEL_DIM)
            y0 = y
            y = self._line(screen, f"Wage: {fmt(posting.wage)}/day", y,
                           small=True)
            bx = self.rect.right - 116
            for label, delta in (("-", -25), ("+", +25)):
                def adj(dl=delta):
                    posting.wage = max(25, posting.wage + dl)
                self.buttons.draw(screen, pygame.Rect(bx, y0, 22, 18),
                                  label, adj)
                bx += 26
            def toggle_strict():
                posting.strict = not posting.strict
                self.notify("Strict: only qualified candidates"
                            if posting.strict else
                            "Lax: anyone may take it (slower if unqualified)")
            self.buttons.draw(
                screen, pygame.Rect(x, y, 150, 18),
                f"Strict: {'ON' if posting.strict else 'off'}",
                toggle_strict)
            def do_cancel():
                world.cancel_posting(posting)
                self.notify("Posting withdrawn")
            self.buttons.draw(screen, pygame.Rect(x + 158, y, 110, 18),
                              "Cancel posting", do_cancel)
            y += 24

        self._draw_operation_policy(screen, machine, y)

    def _draw_operation_policy(self, screen, machine, y: int) -> int:
        """When should this machine run, and who feeds it."""
        x = self.rect.x + 12
        y = self._header(screen, "OPERATION", y)
        y0 = y
        y = self._line(screen, f"Priority: {machine.priority}  (staffed "
                       "high-to-low)", y, small=True)
        bx = self.rect.right - 64
        for label, delta in (("-", -1), ("+", +1)):
            def adj_pri(dl=delta):
                machine.priority += dl
            self.buttons.draw(screen, pygame.Rect(bx, y0, 22, 18), label,
                              adj_pri)
            bx += 26
        def toggle_buy():
            machine.auto_buy = not machine.auto_buy
            self.notify("Will order missing inputs daily"
                        if machine.auto_buy else
                        "Runs only on materials you supply")
        self.buttons.draw(screen, pygame.Rect(x, y, 240, 18),
                          f"Auto-buy inputs: "
                          f"{'ON' if machine.auto_buy else 'off'}",
                          toggle_buy)
        y += 22
        caps = [None, 5, 10, 20, 50, 100]
        def cycle_cap():
            i = (caps.index(machine.max_stock)
                 if machine.max_stock in caps else 0)
            machine.max_stock = caps[(i + 1) % len(caps)]
        cap = ("always run" if machine.max_stock is None
               else f"keep {machine.max_stock}/output")
        self.buttons.draw(screen, pygame.Rect(x, y, 240, 18),
                          f"Output stockpile: {cap}", cycle_cap)
        y += 22
        stops = [None, 0.9, 0.75, 0.5]
        def cycle_stop():
            i = (stops.index(machine.storage_stop)
                 if machine.storage_stop in stops else 0)
            machine.storage_stop = stops[(i + 1) % len(stops)]
        stop = ("off" if machine.storage_stop is None
                else f"at {machine.storage_stop:.0%} full")
        self.buttons.draw(screen, pygame.Rect(x, y, 240, 18),
                          f"Stop when parcel storage: {stop}", cycle_stop)
        y += 26

        def close():
            self.manage_machine = None
        self.buttons.draw(screen, pygame.Rect(x, y + 6, 80, 22), "Back",
                          close)
        return y

    def _draw_build_menu(self, screen, world: World, owner, plot: Plot,
                         y: int) -> None:
        y = self._header(screen, f"BUILD IN SLOT {self.build_slot + 1}", y)
        y = self._line(screen, "Machines are products: have the kit", y,
                       small=True, color=assets.PANEL_DIM)
        y = self._line(screen, "delivered here, then erect it.", y,
                       small=True, color=assets.PANEL_DIM)
        from ..sim import trade as trade_mod
        for mdef in MACHINES:
            y0 = y
            has_kit_product = mdef.id in PRODUCTS
            kits_here = (plot.inventory.get(mdef.id, 0)
                         if has_kit_product else 0)
            inbound = (owner.inbound_to(plot, mdef.id)
                       if has_kit_product else 0)
            raise_cost = cents(mdef.build_cost) if mdef.natural else None
            quote = None
            if not kits_here and not inbound and has_kit_product:
                # best_quote pits sellers against the player's own kits on
                # other parcels -- when shipping your own kit is cheapest,
                # the button becomes a one-click "ship & build".
                quote = trade_mod.best_quote(world, owner, mdef.id, 1, plot)
            tag = ("kit here" if kits_here else
                   "kit en route" if inbound else
                   "natural" if mdef.natural else "no kit")
            y = self._line(screen, f"{mdef.name}  ({tag})", y)
            y = self._line(screen, machine_def_text(mdef), y, small=True,
                           color=assets.PANEL_DIM)

            def do_build(d=mdef):
                if world.build_machine(owner, plot, d.id) is not None:
                    self.notify(f"Built {d.name}")
                    self.build_slot = None
                else:
                    self.notify("Not enough coin")

            def do_order(d=mdef, p=plot):
                if trade_mod.buy(world, owner, d.id, qty=1, dest=p):
                    # Auto-build on arrival, pinned to this parcel.
                    owner.pending_build = d.id
                    owner.pending_build_day = world.day
                    owner.pending_build_plot = p.id
                    self.notify(f"{d.name} kit on the way -- builds "
                                "here on arrival")
                else:
                    self.notify("None for sale -- workshops will "
                                "hear of your request")

            # One button, the cheapest route to a working machine here:
            # an on-site kit is free; then a shipped/bought kit if it
            # beats raising from raw land; then raising; then a request.
            row = pygame.Rect(self.rect.right - 130, y0, 118, 20)
            if kits_here:
                self.buttons.draw(screen, row, "Build (kit here)", do_build)
            elif inbound:
                pass  # arrives and erects itself (pinned pending build)
            elif quote is not None and (raise_cost is None
                                        or quote.unit_cost < raise_cost):
                verb = ("Ship kit" if quote.offer.seller is owner else "Buy")
                self.buttons.draw(screen, row,
                                  f"{verb} {fmt(int(quote.unit_cost))}",
                                  do_order)
            elif raise_cost is not None:
                self.buttons.draw(screen, row, f"Raise {fmt(raise_cost)}",
                                  do_build, enabled=owner.money >= raise_cost)
            else:
                self.buttons.draw(screen, row, "Request", do_order)
            y += 6
        def cancel():
            self.build_slot = None
        self.buttons.draw(screen,
                          pygame.Rect(self.rect.x + 12, y + 8, 80, 22),
                          "Cancel", cancel)

    # --- moving & crafting -----------------------------------------------------
    MOVE_QTYS = (1, 5, 25, None)  # None = the whole stack

    def _draw_move_menu(self, screen, world: World, owner, plot: Plot,
                        y: int) -> None:
        from ..sim import trade as trade_mod
        pid = self.move_pid
        prod = PRODUCTS.get(pid)
        have = plot.inventory.get(pid, 0)
        x = self.rect.x + 12
        y = self._header(screen, f"MOVE {prod.name.upper()} ({have} here)", y)
        choice = self.MOVE_QTYS[self.move_qty_i]
        qty = have if choice is None else min(choice, have)
        def cycle_qty():
            self.move_qty_i = (self.move_qty_i + 1) % len(self.MOVE_QTYS)
        self.buttons.draw(screen, pygame.Rect(x, y, 160, 20),
                          f"Quantity: {'all' if choice is None else qty}",
                          cycle_qty)
        y += 26
        y = self._line(screen, "Your goods, your cart, paid trip:",
                       y, small=True, color=assets.PANEL_DIM)
        for dest in owner.plots:
            if dest is plot:
                continue
            tag = "home" if dest is owner.home else (
                dest.machines()[0].definition.name if dest.machines()
                else "empty")
            quote = trade_mod.transfer_quote(world, owner, pid, qty,
                                             plot, dest)
            if quote is None:
                label = f"-> parcel {dest.id} ({tag}): no room or no cart"
                self.buttons.draw(screen, pygame.Rect(x, y, 260, 18),
                                  label, lambda: None, enabled=False)
            else:
                def do_move(d=dest, q=qty):
                    sent = trade_mod.transfer(world, owner, pid, q, plot, d)
                    if sent:
                        self.notify(f"{sent} {prod.name} on the way")
                    else:
                        self.notify("No idle vehicle for the trip")
                label = (f"-> parcel {dest.id} ({tag}): {quote.qty} for "
                         f"{fmt(quote.trip_cost)}")
                self.buttons.draw(screen, pygame.Rect(x, y, 260, 18),
                                  label, do_move)
            y += 22
        if len(owner.plots) < 2:
            y = self._line(screen, "(you own no other parcel)", y,
                           small=True, color=assets.PANEL_DIM)
        def close():
            self.move_pid = None
        self.buttons.draw(screen, pygame.Rect(x, y + 8, 80, 22), "Back",
                          close)

    def _missing_inputs(self, plot, recipe) -> dict:
        return {p: q - plot.inventory.get(p, 0)
                for p, q in recipe.inputs.items()
                if plot.inventory.get(p, 0) < q}

    def _fetch_quotes(self, world, owner, plot, missing):
        """(total trip cents, all coverable): preview of shipping missing
        inputs in from the owner's other parcels."""
        from ..sim import trade as trade_mod
        total, possible = 0, True
        for pid, need in missing.items():
            remaining = need
            for src in owner.plots:
                if src is plot or remaining <= 0:
                    continue
                have = src.inventory.get(pid, 0)
                if have <= 0:
                    continue
                quote = trade_mod.transfer_quote(
                    world, owner, pid, min(remaining, have), src, plot,
                    respect_capacity=False)
                if quote is None:
                    continue
                total += quote.trip_cost
                remaining -= quote.qty
            if remaining > 0:
                possible = False
        return total, possible

    def _fetch_inputs(self, world, owner, plot, missing) -> bool:
        """Ship missing recipe inputs in from other owned parcels.
        Capacity is ignored: they're bound for the machine, not the
        shelf (the output must fit; the input may overflow)."""
        from ..sim import trade as trade_mod
        any_sent = False
        for pid, need in missing.items():
            remaining = need
            for src in owner.plots:
                if src is plot or remaining <= 0:
                    continue
                have = src.inventory.get(pid, 0)
                if have <= 0:
                    continue
                sent = trade_mod.transfer(world, owner, pid,
                                          min(remaining, have), src, plot,
                                          respect_capacity=False)
                remaining -= sent
                any_sent = any_sent or sent > 0
        return any_sent

    def _draw_craft_menu(self, screen, world: World, owner, plot: Plot,
                         y: int) -> None:
        from ..content import RECIPES
        y = self._header(screen, "CRAFT (this parcel's machines)", y)
        y = self._line(screen, "One-shot batch: runs as soon as inputs and",
                       y, small=True, color=assets.PANEL_DIM)
        y = self._line(screen, "an operator are free, then reverts recipe.",
                       y, small=True, color=assets.PANEL_DIM)
        for machine in plot.machines():
            d = machine.definition
            if not d.recipes:
                continue
            status = (f"busy x{machine.batches}" if machine.batches
                      else "idle")
            y = self._line(screen, f"{d.name}  Lv{machine.level}  ({status})",
                           y)
            for rid in d.recipes:
                r = RECIPES.get(rid)
                y0 = y
                y = self._line(
                    screen,
                    f"{r.name} ({machine.cycle_ticks_for(rid)}t)",
                    y, small=True)
                self.hover_zones.append((
                    pygame.Rect(self.rect.x, y0, self.rect.w, y - y0),
                    [r.name, recipe_line(r),
                     f"{machine.cycle_ticks_for(rid)} ticks on this "
                     f"machine (x{machine.max_batches} batches)"]))
                bx = pygame.Rect(self.rect.right - 110, y0, 98, 18)
                if machine.batches > 0:
                    self.buttons.draw(screen, bx, "busy", lambda: None,
                                      enabled=False)
                    continue
                missing = self._missing_inputs(plot, r)
                if not missing:
                    def do_run(m=machine, rr=rid):
                        if m.queue_manual(rr):
                            self.notify("Queued -- starts when an operator "
                                        "is free")
                        else:
                            self.notify("Finish the current batch first")
                    self.buttons.draw(screen, bx, "Run", do_run)
                elif all(owner.inbound_to(plot, p) >= q
                         for p, q in missing.items()):
                    self.buttons.draw(screen, bx, "en route", lambda: None,
                                      enabled=False)
                else:
                    cost, possible = self._fetch_quotes(world, owner, plot,
                                                        missing)
                    if possible:
                        def do_fetch(m=machine, rr=rid, miss=dict(missing)):
                            if self._fetch_inputs(world, owner, plot, miss):
                                m.queue_manual(rr)
                                self.notify("Materials on the way -- crafts "
                                            "on arrival")
                            else:
                                self.notify("No idle vehicle for the trip")
                        self.buttons.draw(screen, bx, f"Fetch {fmt(cost)}",
                                          do_fetch)
                    else:
                        self.buttons.draw(screen, bx, "no inputs",
                                          lambda: None, enabled=False)
        def close():
            self.craft_open = False
        self.buttons.draw(screen,
                          pygame.Rect(self.rect.x + 12, y + 8, 80, 22),
                          "Back", close)
