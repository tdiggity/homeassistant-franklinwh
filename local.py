"""Local (LAN) data source for the FranklinWH aGate.

Reads the aGate's live power-flow frame directly over TCP/9000 using the
franklinwh-direct-connect-api package (imported as ``franklinwh_local``). This
is the same frame the FranklinWH cloud relays as ``runtimeData``, so the
numbers match the cloud ones, with two differences handled here:

* Power fields (p_*) arrive in watts; the cloud and our sensors use kW.
* ``offgridreason`` is 0 during normal grid-tied operation, whereas the cloud
  library treats 0 as "grid down".

Smart Circuit (switch 1/2) and V2L figures are not in this frame. They come
from a separate cloud request, so callers fill them in when the cloud answers.
"""

from __future__ import annotations

import logging
from typing import Any

import franklinwh
from franklinwh.client import Current, Totals

_LOGGER = logging.getLogger(__name__)

DEFAULT_LOCAL_PORT = 9000
LOCAL_TIMEOUT = 8.0

# offgridreason values seen while the aGate is grid-tied.
_GRID_NORMAL_REASONS = (None, -1, 0)


def read_power_flow(host: str, port: int, timeout: float = LOCAL_TIMEOUT) -> dict[str, Any]:
    """Blocking: connect, log in, read one power-flow frame, close."""
    # Imported here so a missing package only breaks the local path.
    from franklinwh_local import LocalClient  # noqa: PLC0415

    client = LocalClient(host, port, timeout=timeout, retries=1)
    try:
        client.transport.connect()
        client.login()
        return dict(client.power_flow())
    finally:
        try:
            client.transport.close()
        except Exception:  # noqa: BLE001
            pass


def _num(pf: dict[str, Any], key: str, scale: float = 1.0) -> float | None:
    value = pf.get(key)
    if value is None:
        return None
    try:
        return float(value) * scale
    except (TypeError, ValueError):
        return None


def _round(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)


def grid_status_from_local(pf: dict[str, Any]) -> franklinwh.GridStatus:
    """Map the local offgridreason to a GridStatus."""
    reason = pf.get("offgridreason")
    if reason in _GRID_NORMAL_REASONS:
        return franklinwh.GridStatus.NORMAL
    _LOGGER.warning(
        "FranklinWH local: off-grid reason %r (elecnet_state=%r, main_sw=%r); "
        "reporting grid as DOWN",
        reason,
        pf.get("elecnet_state"),
        pf.get("main_sw"),
    )
    return franklinwh.GridStatus.DOWN


def stats_from_local(
    pf: dict[str, Any], switch_usage: dict[str, Any] | None = None
) -> franklinwh.Stats:
    """Build a franklinwh.Stats from a local power-flow frame.

    ``switch_usage`` is the cloud's smart-circuit reply (cmd 353), if one was
    fetched; without it the switch and V2L sensors read unknown.
    """
    if pf.get("soc") is None or pf.get("p_load") is None:
        raise ValueError(f"local power-flow frame is missing core fields: {sorted(pf)}")

    sw = switch_usage or {}
    kw = 1 / 1000.0
    gen_stat = pf.get("genStat")

    return franklinwh.Stats(
        Current(
            solar_production=_num(pf, "p_sun", kw),
            generator_production=_num(pf, "p_gen", kw),
            generator_enabled=bool(gen_stat is not None and gen_stat > 1),
            battery_use=_num(pf, "p_fhp", kw),
            grid_use=_num(pf, "p_uti", kw),
            home_load=_num(pf, "p_load", kw),
            # The aGate reports SOC at full float precision (68.3684158325195).
            battery_soc=_round(_num(pf, "soc"), 1),
            switch_1_load=sw.get("SW1ExpPower"),
            switch_2_load=sw.get("SW2ExpPower"),
            v2l_use=sw.get("CarSWPower"),
            grid_status=grid_status_from_local(pf),
        ),
        Totals(
            battery_charge=_num(pf, "kwh_fhp_chg"),
            battery_discharge=_num(pf, "kwh_fhp_di"),
            grid_import=_num(pf, "kwh_uti_in"),
            grid_export=_num(pf, "kwh_uti_out"),
            solar=_num(pf, "kwh_sun"),
            generator=_num(pf, "kwh_gen"),
            home_use=_num(pf, "kwh_load"),
            switch_1_use=sw.get("SW1ExpEnergy"),
            switch_2_use=sw.get("SW2ExpEnergy"),
            v2l_export=sw.get("CarSWExpEnergy"),
            v2l_import=sw.get("CarSWImpEnergy"),
        ),
    )
