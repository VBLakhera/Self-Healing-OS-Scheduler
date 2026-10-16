import argparse
import os
import random
import tempfile
import time

PAGE = 4096


def page_in(buf):
    buf[::PAGE] = b"\x01" * (-(-len(buf) // PAGE))


def churn(seconds, tmp):
    buf = bytearray(random.randint(200_000, 300_000))
    page_in(buf)
    end = time.time() + seconds
    while time.time() < end:
        buf = bytearray(random.randint(200_000, 300_000))
        page_in(buf)
        with open(os.path.join(tmp, "scratch.tmp"), "w"):
            pass
        print("warmup, %ds left" % (end - time.time()), flush=True)
        time.sleep(1)


def leak(mb, tmp):
    mem = []
    files = []
    chunk = mb * 1024 * 1024
    while True:
        b = bytearray(chunk)
        page_in(b)
        mem.append(b)
        files.append(open(os.path.join(tmp, "leak_%05d.tmp" % len(files)), "w"))
        print("leaked %dMB, %d files held open" % (len(mem) * mb, len(files)), flush=True)
        time.sleep(1)


def main():
    ap = argparse.ArgumentParser(description="a leaky process for the demo")
    ap.add_argument("mb_per_sec", nargs="?", type=int, default=5)
    ap.add_argument("--warmup", type=float, default=0.0)
    args = ap.parse_args()

    tmp = tempfile.mkdtemp(prefix="leak_demo_")
    print("pid %d, %ds warmup then leaking %dMB/s"
          % (os.getpid(), args.warmup, args.mb_per_sec), flush=True)
    try:
        if args.warmup > 0:
            churn(args.warmup, tmp)
        leak(args.mb_per_sec, tmp)
    except KeyboardInterrupt:
        print("stopped", flush=True)


if __name__ == "__main__":
    main()
