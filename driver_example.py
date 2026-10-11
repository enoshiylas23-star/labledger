import argparse
import csv
import io
import json
import math
import random
import socket
import sys
import urllib.request


def demo_csv(compound="Caffeine"):
    bands = {"Caffeine": [(272, 1.0, 12.0), (205, 0.6, 9.0)],
             "Benzoic acid": [(230, 1.0, 8.0), (275, 0.35, 10.0)]}.get(compound, [(272, 1.0, 12.0)])
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["wavelength_nm", "absorbance_A"])
    rng = random.Random(7)
    for wl in range(200, 401, 2):
        a = sum(rel * math.exp(-((wl - mu) ** 2) / (2 * sig * sig)) for mu, rel, sig in bands) * 0.72
        a += rng.gauss(0, 0.0018)
        w.writerow([wl, round(max(0.0, a), 4)])
    return buf.getvalue()


def send_tcp(host, port, payload, timeout=5.0):
    with socket.create_connection((host, port), timeout=timeout) as s:
        s.sendall(json.dumps(payload).encode() + b"\n")
        buf = b""
        while b"\n" not in buf:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
        return json.loads(buf.decode() or "{}")


def send_http(base, payload, timeout=5.0):
    req = urllib.request.Request(
        base.rstrip("/") + "/api/ingest",
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def main():
    ap = argparse.ArgumentParser(description="LabLedger instrument driver example")
    ap.add_argument("--mode", choices=["tcp", "http"], default="tcp")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5056)
    ap.add_argument("--http-base", default="http://127.0.0.1:5000")
    ap.add_argument("--api-key", required=True, help="API key from the Instruments page")
    ap.add_argument("--instrument", default="LC-2030 #3")
    ap.add_argument("--compound", default="Caffeine")
    ap.add_argument("--csv", help="Path to a CSV file (wavelength_nm,absorbance_A)")
    ap.add_argument("--demo", action="store_true", help="Send a generated demo spectrum")
    args = ap.parse_args()

    if args.csv:
        with open(args.csv, "r", encoding="utf-8") as f:
            csv_text = f.read()
    elif args.demo:
        csv_text = demo_csv(args.compound)
    else:
        print("Provide --csv FILE or --demo", file=sys.stderr)
        sys.exit(2)

    payload = {"api_key": args.api_key, "instrument": args.instrument,
               "compound": args.compound, "kind": "spectrum", "csv": csv_text}
    if args.mode == "tcp":
        result = send_tcp(args.host, args.port, payload)
    else:
        result = send_http(args.http_base, payload)
    print(json.dumps(result, indent=2))
    if not result.get("ok"):
        sys.exit(1)


if __name__ == "__main__":
    main()
