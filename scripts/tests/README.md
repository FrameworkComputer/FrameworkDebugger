# EC hardware-in-the-loop tests

Smoke tests for an EC connected through a Bus Pirate 5 (wiring in
`../ectarget.py`). The BP5 must be in BPIO2 binmode.

```sh
cd scripts
nix-shell                                   # or any env with pyserial, flatbuffers, cobs, pytest
pytest --ec-build ~/clone/ec/result         # flash the build, then test it
pytest                                      # test whatever is already on the EC
pytest -k reboot --ec-log /tmp/ec.log       # subset, custom console log
```

Each test's start is marked in the console log (`### test ...`).
New tests get an `ec` fixture (`ectarget.EcTarget`) with `boot()`,
`expect()`, `command()`, `reset()` and `flash()`.
