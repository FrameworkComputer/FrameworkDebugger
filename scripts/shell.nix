{ pkgs ? import <nixpkgs> {} }:

(pkgs.buildFHSEnv {
  name = "framework-debugger-shell";
  targetPkgs = pkgs: with pkgs; [
    (python3.withPackages (ps: [ ps.pyserial ps.flatbuffers ps.cobs ps.numpy ]))
    libftdi1
    libusb1
  ];
  runScript = "bash";
}).env
