# Demo Agent App Package

This package is separate from the repository's existing declarative agent.

It registers the Python `demo_agent` web host as a Teams/Microsoft 365 app with:

- A Bot Framework endpoint at `/api/messages`.
- A personal Control Plane tab at `/control-plane`.
- The same Entra Agent ID and Blueprint correlation used by the autonomous runtime.

Package variables are filled from `appPackage/.env.dev` during `atk package`.