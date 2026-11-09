# BLE-Session zum inVENTer Pulsar (aioble, Central / GATT-Client).
# Erlaubte Schreibzugriffe: PIN, Boost, Sensorik Byte 0. Sonst nichts.
# Die PIN wird nie geloggt.

import asyncio
import struct

import aioble
import bluetooth

from config import PIN, PULSAR_ADDR

CONNECT_TIMEOUT_MS = 12000
CONNECT_ATTEMPTS = 2  # schwaches Signal: ein zweiter Versuch vor dem roten Kreuz
BOOST_RPM = 2400  # Quick-Boost der Hersteller-App

AUTH_SVC = bluetooth.UUID("e6834e4b-7b3a-48e6-91e4-f1d005f564d3")
PIN_CHR = bluetooth.UUID("4cad343a-209a-40b7-b911-4d9b3df569b2")
PIN_OK_CHR = bluetooth.UUID("d1ae6b70-ee12-4f6d-b166-d2063dcaffe1")
CFG_SVC = bluetooth.UUID("c119e858-0531-4681-9674-5a11f0e53bb4")
BOOST_CHR = bluetooth.UUID("118c949c-28c8-4139-b0b3-36657fd055a9")
SENS_CHR = bluetooth.UUID("e782e131-6ce1-4191-a8db-f4304d7610f1")


class PulsarError(Exception):
    def __init__(self, msg, maybe_written=False):
        super().__init__(msg)
        self.maybe_written = maybe_written


def _addr():
    return bytes(int(x, 16) for x in PULSAR_ADDR.split(":"))


async def _read_boost(chr_):
    b = bytes(await chr_.read())
    if len(b) < 5:
        raise PulsarError("boost: %d Byte" % len(b))
    return struct.unpack("<BHH", b[:5])


async def run(ops):
    """Verbinden, PIN, ops ausfuehren, Boost lesen, trennen.
    ops: [("boost", sekunden|0), ("boost_extend", sekunden), ("humidity", bool)]
    Rueckgabe: (boost_aktiv, restsekunden)."""
    dev = aioble.Device(aioble.ADDR_PUBLIC, _addr())
    conn = None
    for attempt in range(CONNECT_ATTEMPTS):
        try:
            conn = await dev.connect(timeout_ms=CONNECT_TIMEOUT_MS)
            break
        except Exception as e:
            print("connect-versuch %d: %r" % (attempt + 1, e))
            if attempt + 1 == CONNECT_ATTEMPTS:
                raise PulsarError("connect: %r" % e)
            await asyncio.sleep_ms(500)

    written = False
    try:
        async with conn:
            auth = await conn.service(AUTH_SVC)
            if auth is None:
                raise PulsarError("auth-service fehlt")
            await (await auth.characteristic(PIN_CHR)).write(struct.pack("<I", PIN), response=True)
            ok = bytes(await (await auth.characteristic(PIN_OK_CHR)).read())
            if ok[:1] != b"\x01":
                raise PulsarError("PIN abgelehnt (%r)" % ok)

            cfg = await conn.service(CFG_SVC)
            if cfg is None:
                raise PulsarError("config-service fehlt")
            boost = await cfg.characteristic(BOOST_CHR)
            sens = await cfg.characteristic(SENS_CHR)

            for op, arg in ops:
                if op == "boost":
                    val = (1, BOOST_RPM, arg) if arg > 0 else (0, 0, 0)
                    written = True
                    await boost.write(struct.pack("<BHH", *val), response=True)
                elif op == "boost_extend":
                    active, _rpm, rem = await _read_boost(boost)
                    new = min(rem + arg, 65535) if active else arg
                    written = True
                    await boost.write(struct.pack("<BHH", 1, BOOST_RPM, new), response=True)
                elif op == "humidity":
                    s = bytes(await sens.read())
                    if len(s) < 4 or s[0] not in (0, 1):
                        raise PulsarError("sensorik unerwartet: %r" % s, written)
                    target = 1 if arg else 0
                    if s[0] != target:
                        written = True
                        await sens.write(bytes((target,)) + s[1:4], response=True)
                        check = bytes(await sens.read())
                        if check[:1] != bytes((target,)):
                            raise PulsarError("sensorik nicht uebernommen: %r" % check, True)
                else:
                    raise PulsarError("unbekannte op %r" % op)

            active, _rpm, rem = await _read_boost(boost)
            return (bool(active), rem)
    except PulsarError as e:
        e.maybe_written = e.maybe_written or written
        raise
    except Exception as e:
        raise PulsarError("ble: %r" % e, written)
