{ pkgs ? import <nixpkgs> {} }:

(pkgs.buildFHSEnv {
  name = "framework-debugger-shell";
  targetPkgs = pkgs: with pkgs; [
    libftdi1
    libusb1
  ];
  runScript = "bash";
}).env
