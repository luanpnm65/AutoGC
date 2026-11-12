"""Manage a verified batch of single Hero or Castle Tower diamond upgrades."""

from contextlib import contextmanager
from dataclasses import asdict, dataclass
import json


GEM_THRESHOLD = 50
UPGRADE_COUNT = 50
VALID_COSTS = (1, 2, 3)
HERO_SLOT = (461, 92)
TOWER_LAYER_TOGGLE = (380, 457)
LIGHTNING_LAYER = (380, 366)
EXIT_LAYER_VIEW = (550, 90)
LV_UP = (896, 470)
DETAIL_CLOSE = (994, 160)
LIST_CLOSE = (1247, 76)


@dataclass(frozen=True)
class Action:
    name: str
    point: tuple[int, int] | None = None
    charge: tuple[int, int, int] | None = None
    raw_point: bool = False
    keyevent: int | None = None


@dataclass
class Batch:
    gems: int
    level: int
    restore_hero: bool
    confirmed: int = 0
    pending_cost: int | None = None
    done: bool = False
    closed: bool = False

    def validate(self):
        if (type(self.gems) is not int or self.gems < 0
                or type(self.level) is not int or self.level < 1
                or type(self.confirmed) is not int or not 0 <= self.confirmed <= UPGRADE_COUNT
                or type(self.restore_hero) is not bool
                or type(self.done) is not bool
                or type(self.closed) is not bool
                or (self.pending_cost is not None
                    and (type(self.pending_cost) is not int or self.pending_cost not in VALID_COSTS))
                or (self.pending_cost is not None and (self.confirmed == UPGRADE_COUNT or self.done))
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
    def __init__(self, report, journal=None, *, target="tower"):
        if target not in {"hero", "tower"}:
            raise ValueError(f"Unsupported upgrade target: {target!r}")
        self.target = target
        self.label = "Hero" if target == "hero" else "Tower"
        self.report = report
        self.journal = journal
        self.batch = None
        if journal is not None and journal.exists():
            data = json.loads(journal.read_text(encoding="utf-8"))
            if data is not None:
                try:
                    self.batch = Batch(**data)
                except TypeError as exc:
                    raise ValueError("Invalid upgrade journal") from exc
                self.batch.validate()
                if self.batch.confirmed >= UPGRADE_COUNT or self.batch.closed:
                    self.batch.done = True
        self.active = self.batch is not None and not self.batch.closed
        self.restore_hero = self.batch is not None and self.batch.restore_hero
        self.rearmed_by_battle = False
        self.navigation = None
        self.observation = None
        self.since = 0
        self.unverified_since = None

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
        if not self.active and self.batch is not None:
            self.rearmed_by_battle = True

    def wait_for_reading(self, time, message):
        if self.unverified_since is None:
            self.unverified_since = time
        elif time - self.unverified_since > 5:
            raise RuntimeError(message)
        return True, None

    def _complete_batch(self, time, name, layout, early_reason=None):
        if self.batch is not None and not self.batch.done:
            self.batch.done = True
            self.save()
            if early_reason:
                self.report(time, early_reason)
        return self.finish(time, name, layout)

    def feed(self, time, screen):
        reading = (screen.name, screen.gems, screen.layout, screen.level, screen.cost)
        if reading != self.observation:
            self.observation, self.since = reading, time
        stable = time - self.since >= 0.18
        name, gems, layout, level, cost = reading

        if not self.active:
            if self.batch is not None:
                rearmed = (
                    self.rearmed_by_battle
                    or (name in {"home", "gold"} and stable and gems is not None and gems < GEM_THRESHOLD)
                )
                if self.batch.gems >= GEM_THRESHOLD and not rearmed:
                    return False, None
                self.batch = None
                self.restore_hero = False
                self.rearmed_by_battle = False
                self.save()
            if (name not in {"home", "tower"} or not stable
                    or gems is None or gems < GEM_THRESHOLD):
                return False, None
            self.active = True
            self.rearmed_by_battle = False
            self.report(time, f"{self.label} upgrade triggered at {gems} white gems")

        if self.navigation:
            started, expected, expected_layout = self.navigation
            matches = name == expected or (expected == "castles" and name == "home")
            if matches and (expected_layout is None or layout == expected_layout):
                if not stable:
                    return True, None
                self.navigation = None
            elif time - started > 5:
                raise RuntimeError(f"{self.label} upgrade stopped while waiting for {expected}.")
            else:
                return True, None
        if not stable:
            return self.wait_for_reading(time, f"{self.label} upgrade stopped: screen did not stabilize.")

        if self.batch is not None and (self.batch.done or self.batch.confirmed >= UPGRADE_COUNT):
            return self.finish(time, name, layout)

        if name == "home":
            if self.target == "hero":
                if layout == "castle":
                    return self.navigate(time, "restore hero slots", EXIT_LAYER_VIEW, "home", "hero")
                if layout == "hero":
                    return self.navigate(time, "open top-right Hero", HERO_SLOT, "tower")
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
                time, f"{self.label} upgrade stopped: open the verified {self.label} detail panel."
            )

        if self.batch is None:
            if gems < GEM_THRESHOLD:
                raise RuntimeError(
                    f"{self.label} upgrade stopped: white gem balance fell below {GEM_THRESHOLD} before the batch."
                )
            if cost not in VALID_COSTS:
                return self.wait_for_reading(
                    time, f"{self.label} upgrade stopped: single-upgrade diamond price is unverified."
                )
            if gems < cost:
                return self._complete_batch(
                    time, name, layout,
                    f"{self.label} upgrade stopped before tapping ({gems} white gems < {cost}): closing menu",
                )
            self.batch = Batch(gems, level, self.restore_hero)
            self.save()

        batch = self.batch
        if batch.pending_cost is not None:
            if (gems, level) != (batch.gems - batch.pending_cost, batch.level + 1):
                return self.wait_for_reading(
                    time, f"{self.label} upgrade stopped at {batch.confirmed}/{UPGRADE_COUNT}: "
                    "last tap is unconfirmed; inspect the level and gem balance before restarting."
                )
            batch.gems, batch.level = gems, level
            batch.pending_cost = None
            batch.confirmed += 1
            self.save()
            self.report(
                time,
                f"{self.label} {batch.confirmed}/{UPGRADE_COUNT} confirmed (level {level}, {gems} white gems)",
            )
            self.unverified_since = None
            if batch.confirmed >= UPGRADE_COUNT:
                return self._complete_batch(time, name, layout)
            if gems == 0 or (cost in VALID_COSTS and gems < cost):
                return self._complete_batch(
                    time, name, layout,
                    f"{self.label} stopped at {batch.confirmed}/{UPGRADE_COUNT} "
                    f"({gems} white gems remaining): closing menu",
                )

        if (gems, level) != (batch.gems, batch.level):
            return self.wait_for_reading(
                time, f"{self.label} upgrade stopped: level or balance is unverified."
            )
        if gems == 0 or (cost in VALID_COSTS and gems < cost):
            return self._complete_batch(
                time, name, layout,
                f"{self.label} stopped at {batch.confirmed}/{UPGRADE_COUNT} "
                f"({gems} white gems remaining): closing menu",
            )
        if cost not in VALID_COSTS:
            return self.wait_for_reading(
                time, f"{self.label} upgrade stopped: single-upgrade diamond price is unverified."
            )

        self.unverified_since = None
        unit = "gem" if cost == 1 else "gems"
        return True, Action(
            f"upgrade {self.label} {batch.confirmed + 1}/{UPGRADE_COUNT} ({cost} {unit})",
            LV_UP,
            (gems, level, cost),
        )

    def record_tap(self, action):
        # Write ahead of the ADB call. A crash leaves a pending tap that can
        # only be resolved by observing the exact resulting level and balance.
        gems, level, cost = action.charge
        batch = self.batch
        if (batch is None or batch.pending_cost is not None or batch.done
                or batch.confirmed >= UPGRADE_COUNT
                or (gems, level) != (batch.gems, batch.level) or cost not in VALID_COSTS):
            raise RuntimeError(f"{self.label} upgrade stopped: journal and planned tap disagree.")
        batch.pending_cost = cost
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
            time, f"{self.label} upgrade finished; close the menu manually."
        )
