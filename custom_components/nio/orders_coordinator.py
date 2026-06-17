"""Slow, separate coordinator for NIO service orders (billing).

Deliberately apart from the status coordinator: different gateway, far lower
cadence (orders change ~weekly), and a one-time throttled backfill of the full
history. The ledger (keyed by ``orderNo``) is persisted to ``.storage`` so the
backfill resumes across restarts and steady-state only refetches the most
recent few — which doubles as catching *changed* old orders (e.g. unpaid →
paid, or → cancelled), since orders are upserted, not appended.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from . import orders as orders_logic
from .api import NioApiError, NioAuthError, NioOrdersClient
from .const import (
    BACKFILL_PAGE_GAP,
    CONF_VEHICLE_ID,
    DEFAULT_INTERVAL_ORDERS,
    DOMAIN,
    OPT_INTERVAL_ORDERS,
    ORDERS_PAGE_SIZE,
    ORDERS_STORAGE_VERSION,
)
from .coordinator import NioConfigEntry
from .orders_statistics import async_import_swap_statistics

_LOGGER = logging.getLogger(__name__)

SYNC_IDLE = "idle"
SYNC_BACKFILLING = "backfilling"
SYNC_UP_TO_DATE = "up_to_date"


class NioOrdersCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetches service orders, persists a ledger, and backfills statistics."""

    config_entry: NioConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: NioConfigEntry,
        client: NioOrdersClient,
    ) -> None:
        hours = int(entry.options.get(OPT_INTERVAL_ORDERS, DEFAULT_INTERVAL_ORDERS))
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_orders",
            update_interval=timedelta(hours=hours),
        )
        self.client = client
        self._vehicle_id = entry.data[CONF_VEHICLE_ID]
        self._store: Store = Store(
            hass, ORDERS_STORAGE_VERSION, f"{DOMAIN}_orders_{entry.entry_id}"
        )
        self._ledger: dict[str, dict] = {}
        self._backfill_complete = False
        self._backfill_offset = 0
        self._backfill_task: asyncio.Task | None = None
        self.sync_status = SYNC_IDLE

    async def async_setup(self) -> None:
        """Load the persisted ledger and kick off backfill if needed.

        Never blocks on the network: the steady-state/backfill fetches run
        afterwards, so a flaky orders gateway can't hold up the integration.
        """
        stored = await self._store.async_load()
        if stored:
            self._ledger = stored.get("ledger") or {}
            self._backfill_complete = bool(stored.get("backfill_complete"))
            self._backfill_offset = int(stored.get("backfill_offset") or 0)
        if self._backfill_complete:
            self.sync_status = SYNC_UP_TO_DATE
        self.async_set_updated_data(self._snapshot())
        if not self._backfill_complete:
            self._start_backfill()

    def _snapshot(self) -> dict[str, Any]:
        snap = orders_logic.aggregate(self._ledger, now_ms=_now_ms())
        snap["sync_status"] = self.sync_status
        snap["order_total"] = len(self._ledger)
        return snap

    async def _persist(self) -> None:
        await self._store.async_save(
            {
                "ledger": self._ledger,
                "backfill_complete": self._backfill_complete,
                "backfill_offset": self._backfill_offset,
            }
        )

    def _import_statistics(self, since_ms: int | None = None) -> None:
        points = orders_logic.build_stat_points(self._ledger, since_ms=since_ms)
        async_import_swap_statistics(self.hass, self._vehicle_id, points)

    def _start_backfill(self) -> None:
        if self._backfill_task and not self._backfill_task.done():
            return
        self.sync_status = SYNC_BACKFILLING
        self._backfill_task = self.config_entry.async_create_background_task(
            self.hass, self._run_backfill(), name=f"{DOMAIN}_orders_backfill"
        )

    async def _run_backfill(self) -> None:
        """Page through *all* history (50/page, a gap between pages).

        Resumable: the offset is persisted after each page, so a restart resumes
        from there. Statistics are imported only on completion — the cumulative
        sums need the oldest orders, which arrive on the last pages.
        """
        try:
            while True:
                orders, has_more = await self.client.async_fetch_page(
                    offset=self._backfill_offset, limit=ORDERS_PAGE_SIZE
                )
                if orders:
                    self._ledger, _ = orders_logic.merge_into_ledger(
                        self._ledger, orders
                    )
                    self._backfill_offset += len(orders)
                    await self._persist()
                    self.async_set_updated_data(self._snapshot())
                if not has_more or not orders:
                    break
                await asyncio.sleep(BACKFILL_PAGE_GAP)
        except (NioAuthError, NioApiError) as err:
            # Non-fatal: pause and leave backfill incomplete. The shared token is
            # also used by the status coordinator, which raises the reauth; on
            # entry reload async_setup re-kicks this from the persisted offset.
            self.sync_status = SYNC_IDLE
            _LOGGER.warning("NIO orders backfill paused: %s", err)
            return

        self._backfill_complete = True
        self.sync_status = SYNC_UP_TO_DATE
        await self._persist()
        self._import_statistics()  # full series now that history is complete
        self.async_set_updated_data(self._snapshot())
        _LOGGER.info("NIO orders backfill complete: %d orders", len(self._ledger))

    async def _async_update_data(self) -> dict[str, Any]:
        """Steady-state tick (12h / manual button): refresh the recent window."""
        if not self._backfill_complete:
            # Backfill owns fetching until history is in, so don't double up — but
            # resume it if a transient (non-auth) error stalled it. _start_backfill
            # is idempotent (a no-op while the task is still running); this also
            # lets the manual "refresh orders" button un-stick a paused backfill.
            self._start_backfill()
            return self._snapshot()
        try:
            recent = await self.client.async_fetch_recent()
        except NioAuthError as err:
            raise ConfigEntryAuthFailed("NIO token rejected (orders)") from err
        except NioApiError as err:
            raise UpdateFailed(str(err)) from err

        self._ledger, dirty_since = orders_logic.merge_into_ledger(self._ledger, recent)
        self.sync_status = SYNC_UP_TO_DATE
        if dirty_since is not None:
            await self._persist()
            self._import_statistics(since_ms=dirty_since)
        return self._snapshot()


def _now_ms() -> int:
    return int(dt_util.utcnow().timestamp() * 1000)
