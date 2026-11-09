# BLE-Scan: listet alle Geraete in Reichweite, markiert den Pulsar.
# Ausfuehren:  mpremote connect <port> run tools/scan.py
import bluetooth, time, ubinascii

PULSAR_SVC = bytes(reversed(bytes.fromhex("e6834e4b7b3a48e691e4f1d005f564d3")))  # LE im Advertising
SECONDS = 15

seen = {}  # addr -> [rssi, name, uuids, is_pulsar]


def parse(adv):
    name, uuids, i = "", [], 0
    while i + 1 < len(adv):
        ln = adv[i]
        if ln == 0:
            break
        t, d = adv[i + 1], bytes(adv[i + 2 : i + 1 + ln])
        if t in (0x08, 0x09):
            name = d.decode("utf-8", "ignore")
        elif t in (0x06, 0x07):
            for j in range(0, len(d), 16):
                uuids.append(d[j : j + 16])
        i += 1 + ln
    return name, uuids


def irq(event, data):
    if event == 5:  # _IRQ_SCAN_RESULT
        addr_type, addr, adv_type, rssi, adv = data
        a = ubinascii.hexlify(bytes(addr), ":").decode()
        name, uuids = parse(bytes(adv))
        e = seen.setdefault(a, [rssi, "", [], False, addr_type])
        e[0] = max(e[0], rssi)
        if name:
            e[1] = name
        e[2] += [u for u in uuids if u not in e[2]]
        if PULSAR_SVC in uuids:
            e[3] = True


ble = bluetooth.BLE()
ble.active(True)
ble.irq(irq)
print("scanne", SECONDS, "s ...")
ble.gap_scan(SECONDS * 1000, 30000, 30000, True)
time.sleep(SECONDS + 1)

print("%d Geraete:" % len(seen))
for a, (rssi, name, uuids, pulsar, at) in sorted(seen.items(), key=lambda kv: -kv[1][0]):
    flag = "  <== PULSAR (Service-UUID)" if pulsar else ""
    print("%s  typ=%d  rssi=%4d  %r%s" % (a, at, rssi, name, flag))
