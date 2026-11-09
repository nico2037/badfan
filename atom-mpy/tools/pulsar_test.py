# Verbindungstest Pulsar. ACTION: "read" (nur lesen) oder "boost_on" / "boost_off".
# Schreibt ausschliesslich PIN und ggf. Boost.
import asyncio, struct, bluetooth, aioble
from config import PIN, PULSAR_ADDR

ACTION = "read"

AUTH_SVC = bluetooth.UUID("e6834e4b-7b3a-48e6-91e4-f1d005f564d3")
PIN_CHR = bluetooth.UUID("4cad343a-209a-40b7-b911-4d9b3df569b2")
PIN_OK_CHR = bluetooth.UUID("d1ae6b70-ee12-4f6d-b166-d2063dcaffe1")
CFG_SVC = bluetooth.UUID("c119e858-0531-4681-9674-5a11f0e53bb4")
BOOST_CHR = bluetooth.UUID("118c949c-28c8-4139-b0b3-36657fd055a9")
SENS_CHR = bluetooth.UUID("e782e131-6ce1-4191-a8db-f4304d7610f1")


def addr_bytes(s):
    return bytes(int(x, 16) for x in s.split(":"))


async def main():
    dev = aioble.Device(aioble.ADDR_PUBLIC, addr_bytes(PULSAR_ADDR))
    for attempt in range(3):
        try:
            print("verbinde (Versuch %d) ..." % (attempt + 1))
            conn = await dev.connect(timeout_ms=10000)
            break
        except Exception as e:
            print("  fehlgeschlagen:", repr(e))
            await asyncio.sleep(2)
    else:
        print("ERGEBNIS: keine Verbindung")
        return
    async with conn:
        print("verbunden")
        auth = await conn.service(AUTH_SVC)
        pin = await auth.characteristic(PIN_CHR)
        await pin.write(struct.pack("<I", PIN), response=True)
        print("PIN geschrieben")
        try:
            ok = await auth.characteristic(PIN_OK_CHR)
            print("PIN-Bestaetigung:", bytes(await ok.read()))
        except Exception as e:
            print("PIN-Bestaetigung nicht lesbar:", repr(e))

        cfg = await conn.service(CFG_SVC)
        boost = await cfg.characteristic(BOOST_CHR)
        sens = await cfg.characteristic(SENS_CHR)
        b = bytes(await boost.read())
        print("Boost roh:", b, "->", struct.unpack("<BHH", b) if len(b) >= 5 else "zu kurz")
        s = bytes(await sens.read())
        print("Sensorik roh:", s)

        if ACTION in ("boost_on", "boost_off"):
            val = (1, 2400, 900) if ACTION == "boost_on" else (0, 0, 0)
            await boost.write(struct.pack("<BHH", *val), response=True)
            await asyncio.sleep_ms(500)
            b = bytes(await boost.read())
            print("Boost nach Schreiben:", struct.unpack("<BHH", b) if len(b) >= 5 else b)
    print("getrennt")


asyncio.run(main())
