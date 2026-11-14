"""Manage a verified batch of Hero or Castle Tower diamond upgrades."""

from contextlib import contextmanager
from dataclasses import asdict, dataclass
import json
import random


_UPGRADE_RNG = random.SystemRandom()


GEM_THRESHOLD = 50
UPGRADE_COUNT = 50
VALID_COSTS = (1, 2, 3)
VALID_BULK_COSTS = range(10, 31)
# Home-screen hero slots, numbered left to right and top to bottom.
HERO_SLOTS = tuple((x, y) for y in (92, 184, 277, 370) for x in (293, 373, 461))
DEFAULT_HERO_SLOT = 3
TOWER_LAYER_TOGGLE = (380, 457)
LIGHTNING_LAYER = (380, 366)
EXIT_LAYER_VIEW = (550, 90)
LV_UP = (896, 470)
LV_UP_10 = (405, 628)
DETAIL_CLOSE = (994, 160)
LIST_CLOSE = (1247, 76)


@dataclass(frozen=True)
class Action:
    name: str
    point: tuple[int, int] | None = None
    charge: tuple[int, int, int, int] | None = None
    raw_point: bool = False
    keyevent: int | None = None


@dataclass
class Batch:
    gems: int
    level: int
    restore_hero: bool
    confirmed: int = 0
    pending_cost: int | None = None
    pending_levels: int = 1
    done: bool = False
    closed: bool = False
    # None denotes a tower batch or a legacy hero journal (slot 3).
    hero_slot: int | None = None

    def validate(self):
        valid_pending = (
            self.pending_cost is None
            or (self.pending_levels == 1
                and type(self.pending_cost) is int and self.pending_cost in VALID_COSTS)
            or (self.pending_levels == 10
                and type(self.pending_cost) is int and self.pending_cost in VALID_BULK_COSTS)
        )
        if (type(self.gems) is not int or self.gems < 0
                or type(self.level) is not int or self.level < 1
                or type(self.confirmed) is not int or self.confirmed < 0
                or type(self.restore_hero) is not bool
                or type(self.pending_levels) is not int or self.pending_levels not in (1, 10)
                or type(self.done) is not bool
                or type(self.closed) is not bool
                or (self.hero_slot is not None
                    and (type(self.hero_slot) is not int or not 1 <= self.hero_slot <= len(HERO_SLOTS)))
                or not valid_pending
                or (self.pending_cost is not None and self.done)
                or (self.closed and self.pending_cost is not None)):
            raise ValueError("Invalid upgrade journal")


@contextmanager
def lock_journal(path, conflict="An upgrade process already owns this emulator journal."):
    if path is None:
        yield
        return
    with path.with_suffix(".lock").open("a+b") as handle:
        handle.seek(0)
        try:
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except ImportError:
            import fcntl

            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise RuntimeError(conflict) from exc
        except OSError as exc:
            raise RuntimeError(conflict) from exc
        yield


class TowerUpgrade:
    def __init__(
        self,
        report,
        journal=None,
        *,
        target="tower",
        hero_slot=DEFAULT_HERO_SLOT,
        gem_threshold=GEM_THRESHOLD,
        upgrade_count=None,
        humanize=False,
        rng=None,
    ):
        if target not in {"hero", "tower"}:
            raise ValueError(f"Unsupported upgrade target: {target!r}")
        if type(hero_slot) is not int or not 1 <= hero_slot <= len(HERO_SLOTS):
            raise ValueError("hero_slot must be an integer between 1 and 12")
        if gem_threshold < 1:
            raise ValueError("gem_threshold must be >= 1")
        max_upgrades = upgrade_count if upgrade_count is not None else max(UPGRADE_COUNT, gem_threshold)
        if max_upgrades < 1:
            raise ValueError("upgrade_count must be >= 1")
        self.target = target
        self.hero_slot = hero_slot
        self.label = "Hero" if target == "hero" else "Tower"
        self.gem_threshold = gem_threshold
        self.upgrade_count = max_upgrades
        self.humanize = humanize
        self.rng = rng or _UPGRADE_RNG
        self.report = report
        self.journal = journal
        self.batch = None
        self.recovered_pending = False
        if journal is not None and journal.exists():
            data = json.loads(journal.read_text(encoding="utf-8"))
            if data is not None:
                try:
                    batch = Batch(**data)
                    batch.validate()
                except (TypeError, ValueError):
                    batch = None
                if batch is not None:
                    # An unfinished journal may refer to a different hero whose detail
                    # panel is still open. Never apply its recovery to another slot.
                    old_slot = batch.hero_slot or DEFAULT_HERO_SLOT
                    if target == "hero" and not batch.closed and old_slot != hero_slot:
                        raise ValueError(
                            f"Unfinished Hero upgrade for slot {old_slot}; restart with "
                            f"--hero-slot {old_slot} and finish it before selecting slot {hero_slot}."
                        )
                    if not batch.closed and batch.pending_cost is None and not batch.done:
                        batch = None
                    else:
                        if batch.confirmed >= self.upgrade_count or batch.closed:
                            batch.done = True
                        self.recovered_pending = batch.pending_cost is not None
                self.batch = batch
                if self.batch is None:
                    self.save()
        self.active = self.batch is not None and not self.batch.closed
        self.restore_hero = self.batch is not None and self.batch.restore_hero
        self.rearmed_by_battle = False
        self.navigation = None
        self.observation = None
        self.since = 0
        self.unverified_since = None
        self.last_seen_time = 0.0
        self.pending_since = None
        self.missed_taps = 0
        self.close_retries = 0
        self.stable_delay = 0.18

    def save(self):
        if self.journal is not None:
            temporary = self.journal.with_suffix(".tmp")
            data = asdict(self.batch) if self.batch else None
            temporary.write_text(json.dumps(data) + "\n", encoding="utf-8")
            temporary.replace(self.journal)

    def navigate(self, time, name, point, expected, layout=None):
        self.navigation = (time, expected, layout)
        return True, Action(name, point)

    def suspend(self):
        self.navigation = None
        self.observation = None
        self.unverified_since = None
        self.pending_since = None
        if not self.active and self.batch is not None:
            self.rearmed_by_battle = True

    def _abort_to_home(self, time, name, layout, message):
        """Abort the current upgrade batch and exit cleanly back to Home so waves resume."""
        self.report(time, f"{message} Exiting upgrade menu to resume play.")
        if self.batch is None:
            self.batch = Batch(self.gem_threshold, 1, self.restore_hero, done=True,
                               hero_slot=self.hero_slot if self.target == "hero" else None)
        else:
            self.batch.pending_cost = None
            self.batch.pending_levels = 1
            self.batch.done = True
        self.save()
        self.navigation = None
        self.unverified_since = None
        self.pending_since = None
        self.missed_taps = 0
        return self.finish(time, name, layout)

    def wait_for_reading(self, time, name, layout, message):
        if self.unverified_since is None:
            self.unverified_since = time
        elif time - self.unverified_since > 4.5:
            if self.batch is not None and self.batch.done:
                # Already trying to exit: force-clear state so main Player loop takes over.
                self.batch.closed = True
                self.save()
                self.active = False
                self.navigation = None
                self.unverified_since = None
                self.report(time, f"{message} Returning control to wave loop.")
                return False, None
            return self._abort_to_home(time, name, layout, message)
        return True, None

    def _complete_batch(self, time, name, layout, early_reason=None):
        if self.batch is not None and not self.batch.done:
            self.batch.pending_cost = None
            self.batch.pending_levels = 1
            self.batch.done = True
            self.save()
            if early_reason:
                self.report(time, early_reason)
        self.pending_since = None
        self.missed_taps = 0
        return self.finish(time, name, layout)

    def feed(self, time, screen, *, allow_start=True):
        self.last_seen_time = time
        reading = (
            screen.name,
            screen.gems,
            screen.layout,
            screen.level,
            screen.cost,
            screen.bulk_cost,
        )
        if reading != self.observation:
            self.observation, self.since = reading, time
            if self.humanize:
                self.stable_delay = (
                    self.rng.uniform(0.50, 0.78)
                    if self.rng.random() < 0.12
                    else self.rng.uniform(0.20, 0.44)
                )
            else:
                self.stable_delay = 0.18
        stable = time - self.since >= self.stable_delay
        name, gems, layout, level, cost, bulk_cost = reading

        if not self.active:
            if not allow_start:
                return False, None
            if self.batch is not None:
                rearmed = (
                    self.rearmed_by_battle
                    or (name in {"home", "gold"} and stable and gems is not None and gems < self.gem_threshold)
                )
                if self.batch.gems >= self.gem_threshold and not rearmed:
                    return False, None
                self.batch = None
                self.restore_hero = False
                self.rearmed_by_battle = False
                self.save()
            if (name not in {"home", "tower"} or not stable
                    or gems is None or gems < self.gem_threshold):
                return False, None
            self.active = True
            self.rearmed_by_battle = False
            self.close_retries = 0
            self.missed_taps = 0
            self.report(
                time,
                f"{self.label} upgrade triggered at {gems} white gems (threshold {self.gem_threshold})",
            )

        if self.navigation:
            started, expected, expected_layout = self.navigation
            matches = name == expected or (expected == "castles" and name == "home")
            if matches and (expected_layout is None or layout == expected_layout):
                if not stable:
                    return True, None
                self.navigation = None
                self.close_retries = 0
            elif time - started > 4.0:
                self.navigation = None
                if self.batch is not None and self.batch.done:
                    self.close_retries += 1
                    if self.close_retries <= 3:
                        return self.finish(time, name, layout)
                    self.batch.closed = True
                    self.save()
                    self.active = False
                    self.report(
                        time,
                        f"{self.label} close menu timed out; returning control to wave loop.",
                    )
                    return False, None
                return self._abort_to_home(
                    time, name, layout,
                    f"{self.label} upgrade timed out while waiting for {expected}.",
                )
            else:
                return True, None
        if not stable:
            return self.wait_for_reading(
                time, name, layout, f"{self.label} upgrade paused: screen did not stabilize."
            )

        if self.batch is not None and (self.batch.done or self.batch.confirmed >= self.upgrade_count):
            return self.finish(time, name, layout)

        if name == "home":
            if self.recovered_pending and gems is not None and gems < self.gem_threshold:
                self.batch = None
                self.active = False
                self.restore_hero = False
                self.recovered_pending = False
                self.save()
                return False, None
            if self.target == "hero":
                if layout == "castle":
                    return self.navigate(time, "restore hero slots", EXIT_LAYER_VIEW, "home", "hero")
                if layout == "hero":
                    return self.navigate(time, f"open Hero slot {self.hero_slot}",
                                         HERO_SLOTS[self.hero_slot - 1], "tower")
            else:
                if layout == "hero":
                    self.restore_hero = True
                    if self.batch is not None:
                        self.batch.restore_hero = True
                        self.save()
                    return self.navigate(time, "show castle layers", TOWER_LAYER_TOGGLE, "home", "castle")
                if layout == "castle":
                    return self.navigate(time, "open Castle tower", LIGHTNING_LAYER, "tower")

        if name != "tower" or gems is None or level is None:
            return self.wait_for_reading(
                time, name, layout,
                f"{self.label} upgrade could not verify the {self.label} detail panel.",
            )

        if self.batch is not None and self.recovered_pending:
            expected_after = (
                self.batch.gems - self.batch.pending_cost,
                self.batch.level + self.batch.pending_levels,
            )
            expected_before = (self.batch.gems, self.batch.level)
            if (gems, level) not in (expected_after, expected_before):
                self.batch = None
            elif (gems, level) == expected_before:
                self.batch.pending_cost = None
                self.batch.pending_levels = 1
                self.save()
            self.recovered_pending = False

        if self.batch is None:
            if gems < self.gem_threshold:
                return self._complete_batch(
                    time, name, layout,
                    f"{self.label} upgrade skipped ({gems} white gems < {self.gem_threshold}): closing menu",
                )
            can_bulk = (
                bulk_cost in VALID_BULK_COSTS
                and gems >= bulk_cost
                and self.upgrade_count >= 10
            )
            if not can_bulk and cost not in VALID_COSTS:
                return self.wait_for_reading(
                    time, name, layout,
                    f"{self.label} upgrade could not read single-upgrade diamond price.",
                )
            if not can_bulk and gems < cost:
                return self._complete_batch(
                    time, name, layout,
                    f"{self.label} upgrade stopped before tapping ({gems} white gems < {cost}): closing menu",
                )
            self.batch = Batch(gems, level, self.restore_hero,
                               hero_slot=self.hero_slot if self.target == "hero" else None)
            self.save()

        batch = self.batch
        if batch.pending_cost is not None:
            expected_after = (
                batch.gems - batch.pending_cost,
                batch.level + batch.pending_levels,
            )
            if (gems, level) != expected_after:
                # If neither level nor gem balance changed after ~0.85s, the game
                # ignored the tap during card bounce; clear pending and retry cleanly.
                if (gems, level) == (batch.gems, batch.level):
                    if self.pending_since is None:
                        self.pending_since = time
                    elif time - self.pending_since >= 0.85:
                        self.missed_taps += 1
                        if self.missed_taps <= 3:
                            batch.pending_cost = None
                            batch.pending_levels = 1
                            self.pending_since = None
                            self.unverified_since = None
                            self.save()
                        else:
                            return self._abort_to_home(
                                time, name, layout,
                                f"{self.label} upgrade tap ignored {self.missed_taps} times at "
                                f"{batch.confirmed}/{self.upgrade_count}.",
                            )
                if batch.pending_cost is not None:
                    return self.wait_for_reading(
                        time, name, layout,
                        f"{self.label} upgrade unconfirmed at {batch.confirmed}/{self.upgrade_count}.",
                    )
            else:
                step_done = batch.pending_levels
                batch.gems, batch.level = gems, level
                batch.pending_cost = None
                batch.pending_levels = 1
                batch.confirmed += step_done
                self.pending_since = None
                self.missed_taps = 0
                self.save()
                step_tag = f" (+{step_done})" if step_done > 1 else ""
                self.report(
                    time,
                    f"{self.label} {batch.confirmed}/{self.upgrade_count}{step_tag} confirmed "
                    f"(level {level}, {gems} white gems)",
                )
                self.unverified_since = None
                if batch.confirmed >= self.upgrade_count:
                    return self._complete_batch(time, name, layout)
                if gems == 0 or (cost in VALID_COSTS and gems < cost):
                    return self._complete_batch(
                        time, name, layout,
                        f"{self.label} stopped at {batch.confirmed}/{self.upgrade_count} "
                        f"({gems} white gems remaining): closing menu",
                    )

        if (gems, level) != (batch.gems, batch.level):
            return self.wait_for_reading(
                time, name, layout,
                f"{self.label} level or gem balance changed unexpectedly.",
            )
        if gems == 0 or (cost in VALID_COSTS and gems < cost):
            return self._complete_batch(
                time, name, layout,
                f"{self.label} stopped at {batch.confirmed}/{self.upgrade_count} "
                f"({gems} white gems remaining): closing menu",
            )

        if (bulk_cost in VALID_BULK_COSTS
                and gems >= bulk_cost
                and self.upgrade_count - batch.confirmed >= 10):
            self.unverified_since = None
            return True, Action(
                f"upgrade {self.label} +10 ({batch.confirmed + 10}/{self.upgrade_count}, {bulk_cost} gems)",
                LV_UP_10,
                (gems, level, bulk_cost, 10),
            )

        if cost not in VALID_COSTS:
            return self.wait_for_reading(
                time, name, layout,
                f"{self.label} single-upgrade diamond price is unverified.",
            )

        self.unverified_since = None
        unit = "gem" if cost == 1 else "gems"
        return True, Action(
            f"upgrade {self.label} {batch.confirmed + 1}/{self.upgrade_count} ({cost} {unit})",
            LV_UP,
            (gems, level, cost, 1),
        )

    def record_tap(self, action):
        # Write ahead of the ADB call. A crash leaves a pending tap that can
        # only be resolved by observing the exact resulting level and balance.
        gems, level, step_cost, step_levels = action.charge
        batch = self.batch
        valid_step = (
            (step_levels == 1 and step_cost in VALID_COSTS)
            or (step_levels == 10 and step_cost in VALID_BULK_COSTS)
        )
        if (batch is None or batch.pending_cost is not None or batch.done
                or batch.confirmed + step_levels > self.upgrade_count
                or (gems, level) != (batch.gems, batch.level)
                or gems < step_cost
                or not valid_step):
            raise RuntimeError(f"{self.label} upgrade stopped: journal and planned tap disagree.")
        batch.pending_cost = step_cost
        batch.pending_levels = step_levels
        self.pending_since = self.last_seen_time
        self.save()

    def finish(self, time, name, layout):
        if name == "tower":
            close_label = "close Hero panel" if self.target == "hero" else "close Tower panel"
            return self.navigate(time, close_label, DETAIL_CLOSE, "castles")
        if name == "castles":
            list_label = "close Heroes list" if self.target == "hero" else "close Castles menu"
            return self.navigate(time, list_label, LIST_CLOSE, "home")
        if name == "home":
            if self.restore_hero and layout == "castle":
                return self.navigate(time, "restore hero slots", EXIT_LAYER_VIEW, "home", "hero")
            if not self.restore_hero or layout == "hero":
                self.batch.closed = True
                self.batch.done = True
                self.save()
                self.active = False
                return True, None
        return self.wait_for_reading(
            time, name, layout, f"{self.label} upgrade finished; waiting for menu to close."
        )
