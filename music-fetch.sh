#!/bin/bash
OUT=/run/tiny-dfr-music
WIDTH=36
POS=0
LAST=""
while true; do
    if [ "$(playerctl status 2>/dev/null)" = "Playing" ]; then
        M=$(playerctl metadata --format '{{artist}} - {{title}}' 2>/dev/null)
    else
        M=""
    fi
    [ "$M" != "$LAST" ] && POS=0 && LAST="$M"
    if [ ${#M} -le $WIDTH ]; then
        echo "$M" > "$OUT"
    else
        PAD="$M   *   "
        LEN=${#PAD}
        OUTSTR="${PAD:$POS:$WIDTH}"
        if [ ${#OUTSTR} -lt $WIDTH ]; then
            OUTSTR="$OUTSTR${PAD:0:$((WIDTH - ${#OUTSTR}))}"
        fi
        echo "$OUTSTR" > "$OUT"
        POS=$(( (POS + 1) % LEN ))
    fi
    sleep 0.4
done
