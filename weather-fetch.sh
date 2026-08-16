#!/bin/bash
OUT=/run/tiny-dfr-weather
W=$(curl -s --max-time 10 "wttr.in/?format=%t+%C" 2>/dev/null)
if [ -n "$W" ] && [ ${#W} -lt 40 ]; then
    echo "$W" | tr -d '+' > "$OUT"
    chmod 644 "$OUT"
fi
