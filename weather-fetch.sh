#!/bin/bash
OUT=/run/tiny-dfr-weather
WIDTH=22
POS=0
W=""
LASTFETCH=0
while true; do
    NOW=$(date +%s)
    if [ $((NOW - LASTFETCH)) -ge 900 ] || [ -z "$W" ]; then
        NEW=$(curl -s --max-time 10 "wttr.in/?format=%t+%C" 2>/dev/null | tr -d '+')
        if [ -n "$NEW" ] && [ ${#NEW} -lt 40 ]; then
            [ "$NEW" != "$W" ] && POS=0
            W="$NEW"
        fi
        LASTFETCH=$NOW
    fi
    if [ ${#W} -le $WIDTH ]; then
        echo "$W" > "$OUT"
    else
        PAD="$W   *   "
        LEN=${#PAD}
        O="${PAD:$POS:$WIDTH}"
        [ ${#O} -lt $WIDTH ] && O="$O${PAD:0:$((WIDTH - ${#O}))}"
        echo "$O" > "$OUT"
        POS=$(( (POS + 1) % LEN ))
    fi
    chmod 644 "$OUT" 2>/dev/null
    sleep 0.5
done
