"""Import battery-swap orders into HA long-term statistics.

Each order carries its real ``createTime``, so the cost/count history can be
backfilled years before the integration was installed. They're registered as
*external* statistics (source ``nio``) rather than entity-backed ones: HA never
auto-generates these, so re-importing the dirty tail after a later order
mutation simply overwrites those hours — no fight with auto-collected stats.

The recorder import is best-effort: a recorder-less HA just skips it.
"""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import DOMAIN, STAT_SWAP_COST, STAT_SWAP_COUNT

_LOGGER = logging.getLogger(__name__)

# object-id suffix → (display name, unit of measurement)
_SPECS: dict[str, tuple[str, str | None]] = {
    STAT_SWAP_COST: ("NIO battery swap cost", "CNY"),
    STAT_SWAP_COUNT: ("NIO battery swap count", None),
}


def async_import_swap_statistics(
    hass: HomeAssistant,
    vehicle_id: str,
    points: dict[str, list[tuple[int, float]]],
) -> None:
    """Push the cost/count series (``{key: [(hour_ms, cumulative_sum), …]}``).

    Statistics are hour-aligned cumulative sums; HA aggregates them into the
    day/month bars shown by the statistics graph card. Idempotent per
    ``(statistic_id, hour)`` — re-importing overwrites, never duplicates.
    """
    try:
        from homeassistant.components.recorder.models import (
            StatisticData,
            StatisticMetaData,
        )
        from homeassistant.components.recorder.statistics import (
            async_add_external_statistics,
        )
    except ImportError:  # recorder not loaded — nothing to import into
        _LOGGER.debug("recorder unavailable; skipping orders statistics")
        return

    # HA 2026.x reworked StatisticMetaData: ``has_mean: bool`` → ``mean_type``
    # enum, and now also wants an explicit ``unit_class`` (None for a currency /
    # plain count — neither is unit-convertible). Both arrived together, so gate
    # them on StatisticMeanType and fall back to the old shape on older cores.
    try:
        from homeassistant.components.recorder.models import StatisticMeanType

        compat_meta: dict = {
            "mean_type": StatisticMeanType.NONE,
            "unit_class": None,
        }
    except ImportError:  # pragma: no cover - older HA without mean_type
        compat_meta = {"has_mean": False}

    for key, (name, unit) in _SPECS.items():
        series = points.get(key) or []
        if not series:
            continue
        statistic_id = f"{DOMAIN}:{vehicle_id}_{key}"
        metadata: StatisticMetaData = {
            **compat_meta,
            "has_sum": True,
            "name": name,
            "source": DOMAIN,
            "statistic_id": statistic_id,
            "unit_of_measurement": unit,
        }
        data: list[StatisticData] = [
            {"start": dt_util.utc_from_timestamp(hour_ms / 1000), "sum": value}
            for hour_ms, value in series
        ]
        async_add_external_statistics(hass, metadata, data)
        _LOGGER.debug("imported %d statistic points into %s", len(data), statistic_id)
