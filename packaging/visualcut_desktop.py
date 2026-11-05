"""Einstieg der gebauten Exe. Siehe src/visualcut/desktop.py."""

import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from visualcut.desktop import main

    main()
