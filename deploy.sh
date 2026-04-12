#!/usr/bin/env bash
# Convenience wrapper – forwards all arguments to deploy/deploy.sh
exec "$(dirname "$0")/deploy/deploy.sh" "$@"
