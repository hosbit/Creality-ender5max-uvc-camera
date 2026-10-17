#!/bin/sh
PID=/var/run/e5m-uvc.pid
LOG=/tmp/e5m-uvc.log
SELF=/usr/data/e5m-uvc-camera.sh

running() {
    [ -s "$PID" ] || return 1
    p=$(cat "$PID")
    case "$p" in ''|*[!0-9]*) return 1 ;; esac
    [ -r "/proc/$p/cmdline" ] || return 1
    tr '\000' ' ' <"/proc/$p/cmdline" | grep -Fq "$SELF run"
}

case "${1:-start}" in
start)
    running && exit 0
    nohup /bin/sh "$SELF" run >/tmp/e5m-uvc-watch.log 2>&1 </dev/null &
    echo $! >"$PID"
    ;;
run)
    child=
    cleanup() {
        trap '' TERM INT
        if [ -n "$child" ]; then
            kill "$child" 2>/dev/null
            wait "$child" 2>/dev/null
        fi
        [ "$(cat "$PID" 2>/dev/null)" = "$$" ] && rm -f "$PID"
        exit 0
    }
    trap cleanup TERM INT
    sleep 15

    while :; do
        if pidof mjpg_streamer >/dev/null 2>&1; then
            sleep 5
            continue
        fi

        dev=
        for f in /sys/class/video4linux/video*/name; do
            [ -r "$f" ] || continue
            [ "$(cat "$f")" = "HDI Webcam USB" ] || continue
            n=${f%/name}
            dev=/dev/${n##*/}
            [ -c "$dev" ] && break
            dev=
        done

        if [ -n "$dev" ]; then
            if netstat -lnt 2>/dev/null | grep -q ':8080[[:space:]]'; then
                sleep 5
                continue
            fi

            LD_LIBRARY_PATH=/usr/lib/mjpg-streamer \
            /usr/bin/mjpg_streamer \
                -i "/usr/lib/mjpg-streamer/input_uvc.so -d $dev -f 5" \
                -o "/usr/lib/mjpg-streamer/output_http.so -p 8080" \
                >"$LOG" 2>&1 &

            child=$!
            wait "$child"
            child=
        fi
        sleep 5
    done
    ;;
stop)
    if running; then
        kill "$p"
    fi
    ;;
status)
    if running; then
        echo "Watcher running: PID $p"
    else
        echo "Watcher stopped"
    fi
    ps | grep '[m]jpg_streamer'
    ;;
*)
    echo "Usage: $SELF start|stop|status"
    exit 1
    ;;
esac
exit 0
