# tiny-dfr with colored buttons

Each Touch Bar button gets its own background color instead of grey.
Tested on MacBook Pro 13" 2019 (A2159, T2) with Zorin OS 18.

## Install

    git clone -b colors https://github.com/The12Ronin/Tiny-dfr-.git ~/tiny-dfr
    cd ~/tiny-dfr && cargo build --release
    sudo systemctl stop tiny-dfr
    sudo install -m755 target/release/tiny-dfr $(command -v tiny-dfr)
    sudo systemctl start tiny-dfr

Needs rustup, the distro cargo is too old.
Set ShowButtonOutlines = true in /etc/tiny-dfr/config.toml or buttons stay black.

## Colors

Edit BUTTON_PALETTE at the top of src/main.rs, then rebuild.
