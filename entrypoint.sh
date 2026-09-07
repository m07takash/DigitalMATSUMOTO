#!/bin/bash
# Container entrypoint.
#
# Deliberately does NOT start any service. The image ships only the *_sample
# templates (see .dockerignore), so a fresh container has no system.env,
# setting.yaml or startup.sh yet — starting Streamlit here would just fail on
# missing credentials. Instead it reports what is still missing and idles, so
# an engineer can exec in, configure, and start the services by hand.
#
# Set DIGIM_AUTOSTART=true to run ./startup.sh instead (only meaningful once
# the configuration files exist, e.g. when they are bind-mounted).

cd /app/DigitalMATSUMOTO || exit 1

_missing=0
_check() {
    if [ -f "$1" ]; then
        printf '  [ok]      %-16s\n' "$1"
    else
        printf '  [MISSING] %-16s  <- cp %s %s\n' "$1" "$2" "$1"
        _missing=1
    fi
}

echo "=================================================================="
echo " DigitalMATSUMOTO container is up. No service has been started."
echo "=================================================================="
echo
echo "Configuration files:"
_check system.env   system.env_sample
_check setting.yaml setting.yaml_sample
_check startup.sh   startup.sh_sample
echo

if [ "$_missing" = "1" ]; then
    echo "Next steps (run inside the container):"
    echo "  docker exec -it <container> bash"
    echo "  cp system.env_sample   system.env    && vi system.env      # API keys, DB"
    echo "  cp setting.yaml_sample setting.yaml  # folder layout, defaults"
    echo "  cp startup.sh_sample   startup.sh    # already executable"
    echo "  ./startup.sh                         # Streamlit :8501 / API :8899"
else
    echo "Configuration looks complete. Start the services with:"
    echo "  docker exec -it <container> bash -c './startup.sh'"
fi
echo

if [ "${DIGIM_AUTOSTART:-false}" = "true" ]; then
    if [ -f startup.sh ]; then
        echo "[entrypoint] DIGIM_AUTOSTART=true -> exec ./startup.sh"
        exec bash ./startup.sh
    fi
    echo "[entrypoint] DIGIM_AUTOSTART=true but startup.sh is absent; idling."
fi

# Hold PID 1 so the container stays up for `docker exec`.
exec tail -f /dev/null
