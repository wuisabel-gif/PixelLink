import argparse
import json
from pathlib import Path
from .core import Transfer, demo_image, load_image, png
from .files import read_regular
from .offline import export_iq, import_iq
from .server import serve


def main():
    p = argparse.ArgumentParser(description='PixelLink: read-only ESP32 + CC1101 telemetry and separate FSK simulator')
    sub = p.add_subparsers(dest='command', required=True)
    s = sub.add_parser('serve', help='Hardware-only loopback dashboard; no generated samples')
    s.add_argument('--port', type=int, default=8000)
    s.add_argument('--serial-port', help='Explicit USB receiver port; read-only 115200 baud')
    s.add_argument('--log', type=Path, help='Exclusive original accepted USB JSONL log, capped at 64 MiB')
    sim = sub.add_parser('simulate', help='Legacy image simulator dashboard, not hardware')
    sim.add_argument('--port', type=int, default=8000)
    sub.add_parser('ports', help='List serial ports without opening them')
    d = sub.add_parser('demo', help='Send demo or supplied image through actual FSK/AWGN')
    d.add_argument('--image', type=Path)
    d.add_argument('--snr', type=float, default=0)
    d.add_argument('--seed', type=int, default=7)
    d.add_argument('--retries', type=int, default=3)
    d.add_argument('--output', type=Path, default=Path('received.png'))
    d.add_argument('--export-iq', type=Path, help='Save first-pass noisy complex64 IQ and JSON sidecar; exclusive creation')
    i = sub.add_parser('import-iq', help='Decode a PixelLink capture with known framing metadata')
    i.add_argument('path', type=Path)
    i.add_argument('--output', type=Path, default=Path('imported.png'))
    h = sub.add_parser('capture-pluto', help='Explicit receive-only unaligned hardware capture; never transmits')
    h.add_argument('--uri', required=True)
    h.add_argument('--frequency', type=int, required=True, help='Receive center frequency in Hz')
    h.add_argument('--sample-rate', type=int, default=1000000)
    h.add_argument('--samples', type=int, default=65536)
    h.add_argument('--gain', type=float, default=20)
    h.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    try:
        if args.command == 'ports':
            from .telemetry_server import list_ports
            print(json.dumps(list_ports(), indent=2))
            return
        if args.command in ('serve', 'simulate'):
            if not 0 <= args.port <= 65535:
                raise ValueError('Port out of range')
            if args.command == 'serve':
                from .telemetry_server import serve as hardware_serve
                hardware_serve(args.port, args.serial_port, args.log)
            else:
                serve(args.port)
            return
        if args.command == 'capture-pluto':
            from .hardware import capture_pluto
            result = capture_pluto(args.output, uri=args.uri, frequency=args.frequency,
                                   sample_rate=args.sample_rate, samples=args.samples, gain=args.gain)
            print(json.dumps(result, indent=2))
            return
        if args.command == 'demo':
            image = load_image(read_regular(args.image, 4*1024*1024)) if args.image else demo_image()
            transfer = Transfer(image, args.seed)
            result = transfer.transmit(args.snr, args.retries)
            if args.export_iq:
                export_iq(transfer, args.export_iq, args.snr)
            data = png(transfer.receiver.image())
            result = {k: v for k, v in result.items() if k not in ('tx', 'rx', 'events', 'trace', 'attempts', 'accepted', 'rows')}
        else:
            receiver, result = import_iq(args.path)
            data = png(receiver.image())
        with args.output.open('xb') as f:
            f.write(data)
        print(json.dumps(result, indent=2))
    except (ValueError, OSError, RuntimeError) as exc:
        p.exit(2, f'PixelLink: {exc}\n')


if __name__ == '__main__':
    main()
