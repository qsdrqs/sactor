{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs = { nixpkgs, ... }:
    let
      pkgs = import nixpkgs {
        config.allowUnfree = true;
        system = "x86_64-linux";
      };
    in
    {
      devShells.x86_64-linux.default =
        pkgs.mkShell
          rec {
            buildInputs = [
              pkgs.gcc
              pkgs.libclang
              pkgs.rustup
              pkgs.zlib
              pkgs.poetry
            ];
            shellHook = with pkgs; ''
              export LD_LIBRARY_PATH="${lib.makeLibraryPath buildInputs}:$LD_LIBRARY_PATH"
              export LD_LIBRARY_PATH="${stdenv.cc.cc.lib.outPath}/lib:$LD_LIBRARY_PATH"
            '';
          };
    };
}
